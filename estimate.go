package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"time"
)

const (
	estimateTimeout      = 25 * time.Second
	estimateMaxUpload    = 8 << 20 // 8 MB
	estimateMaxWorkers   = 2       // MediaPipe makan CPU/RAM, batasi paralelisme
	estimateDefaultDim   = 100.0   // cm, panjang sisi terpanjang frame (default kalibrasi)
	estimateMinDim       = 10.0
	estimateMaxDim       = 500.0
	estimateLowConfBelow = 0.6
	plausibleMinLengthCM = 20.0
	plausibleMaxLengthCM = 130.0
)

var estimateSlots = make(chan struct{}, estimateMaxWorkers)

// pythonResult adalah JSON mentah dari estimate_length.py.
type pythonResult struct {
	Success    bool            `json:"success"`
	LengthCM   float64         `json:"length_cm"`
	Confidence float64         `json:"confidence"`
	PPM        float64         `json:"ppm"`
	Segments   json.RawMessage `json:"segments_px"`
	Error      string          `json:"error"`
}

// estimateResponse adalah kontrak ke client (PWA). Stateless: tidak ada yang ditulis ke DB.
type estimateResponse struct {
	Success        bool            `json:"success"`
	LengthCM       float64         `json:"length_cm,omitempty"`
	Confidence     float64         `json:"confidence,omitempty"`
	PPM            float64         `json:"ppm,omitempty"`
	MaxDimCM       float64         `json:"max_dim_cm,omitempty"`
	Segments       json.RawMessage `json:"segments_px,omitempty"`
	AnnotatedImage string          `json:"annotated_image,omitempty"` // data URL JPEG
	Plausible      bool            `json:"plausible"`
	LowConfidence  bool            `json:"low_confidence"`
	Error          string          `json:"error,omitempty"`
}

func writeEstimate(w http.ResponseWriter, status int, resp estimateResponse) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(resp)
}

// handleEstimateLength: POST multipart {photo, max_dim_cm?} -> estimasi panjang badan via MediaPipe.
// max_dim_cm = panjang nyata (cm) sisi terpanjang foto pada bidang matras (kalibrasi dari client).
func (app *App) handleEstimateLength(w http.ResponseWriter, r *http.Request) {
	select {
	case estimateSlots <- struct{}{}:
		defer func() { <-estimateSlots }()
	default:
		w.Header().Set("Retry-After", "3")
		writeEstimate(w, http.StatusTooManyRequests, estimateResponse{Error: "Server sedang memproses estimasi lain, coba lagi sebentar"})
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, estimateMaxUpload+(1<<20))
	if err := r.ParseMultipartForm(estimateMaxUpload); err != nil {
		writeEstimate(w, http.StatusBadRequest, estimateResponse{Error: "Upload terlalu besar atau tidak valid"})
		return
	}

	maxDim := estimateDefaultDim
	if v := r.FormValue("max_dim_cm"); v != "" {
		parsed, err := strconv.ParseFloat(v, 64)
		if err != nil || !(parsed >= estimateMinDim && parsed <= estimateMaxDim) {
			writeEstimate(w, http.StatusBadRequest, estimateResponse{
				Error: fmt.Sprintf("max_dim_cm harus %.0f-%.0f", estimateMinDim, estimateMaxDim),
			})
			return
		}
		maxDim = parsed
	}

	file, _, err := r.FormFile("photo")
	if err != nil {
		writeEstimate(w, http.StatusBadRequest, estimateResponse{Error: "Field photo wajib diisi"})
		return
	}
	defer file.Close()

	data, err := io.ReadAll(io.LimitReader(file, estimateMaxUpload+1))
	if err != nil || len(data) == 0 || len(data) > estimateMaxUpload {
		writeEstimate(w, http.StatusBadRequest, estimateResponse{Error: "File foto kosong atau terlalu besar"})
		return
	}
	var ext string
	switch http.DetectContentType(data) {
	case "image/jpeg":
		ext = ".jpg"
	case "image/png":
		ext = ".png"
	default:
		writeEstimate(w, http.StatusUnsupportedMediaType, estimateResponse{Error: "Foto harus JPEG atau PNG"})
		return
	}

	tmpDir, err := os.MkdirTemp("", "estimate-")
	if err != nil {
		log.Printf("[estimate] mkdtemp: %v", err)
		writeEstimate(w, http.StatusInternalServerError, estimateResponse{Error: "Server error"})
		return
	}
	defer os.RemoveAll(tmpDir)

	inPath := filepath.Join(tmpDir, "in"+ext)
	outPath := filepath.Join(tmpDir, "out.jpg")
	if err := os.WriteFile(inPath, data, 0600); err != nil {
		log.Printf("[estimate] write temp: %v", err)
		writeEstimate(w, http.StatusInternalServerError, estimateResponse{Error: "Server error"})
		return
	}

	pythonBin := os.Getenv("PYTHON_BIN")
	if pythonBin == "" {
		pythonBin = "python"
	}

	ctx, cancel := context.WithTimeout(r.Context(), estimateTimeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, pythonBin, "estimate_length.py",
		"--image", inPath,
		"--max-dim-cm", strconv.FormatFloat(maxDim, 'f', 2, 64),
		"--output-annotated", outPath,
	)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	runErr := cmd.Run() // exit code 1 itu normal untuk "pose tidak terdeteksi", JSON tetap ada di stdout

	var res pythonResult
	if err := json.Unmarshal(stdout.Bytes(), &res); err != nil {
		log.Printf("[estimate] estimator gagal: run=%v parse=%v stderr=%.500s", runErr, err, stderr.String())
		if ctx.Err() == context.DeadlineExceeded {
			writeEstimate(w, http.StatusGatewayTimeout, estimateResponse{Error: "Estimasi terlalu lama (timeout)"})
			return
		}
		writeEstimate(w, http.StatusBadGateway, estimateResponse{Error: "Estimator tidak tersedia di server (python/mediapipe belum terpasang?)"})
		return
	}

	if !res.Success {
		msg := res.Error
		if msg == "" {
			msg = "Estimasi gagal"
		}
		writeEstimate(w, http.StatusUnprocessableEntity, estimateResponse{Error: msg, MaxDimCM: maxDim})
		return
	}

	resp := estimateResponse{
		Success:       true,
		LengthCM:      res.LengthCM,
		Confidence:    res.Confidence,
		PPM:           res.PPM,
		MaxDimCM:      maxDim,
		Segments:      res.Segments,
		Plausible:     res.LengthCM >= plausibleMinLengthCM && res.LengthCM <= plausibleMaxLengthCM,
		LowConfidence: res.Confidence < estimateLowConfBelow,
	}
	if img, err := os.ReadFile(outPath); err == nil {
		resp.AnnotatedImage = "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(img)
	}
	writeEstimate(w, http.StatusOK, resp)
}
