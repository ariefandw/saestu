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
	Success      bool            `json:"success"`
	Method       string          `json:"method"`
	MethodName   string          `json:"method_name"`
	LengthCM     float64         `json:"length_cm"`
	Confidence   float64         `json:"confidence"`
	PPM          float64         `json:"ppm"`
	MarkerID     *int            `json:"marker_id,omitempty"`
	MarkerSidePX *float64        `json:"marker_side_px,omitempty"`
	MarkerSizeCM *float64        `json:"marker_size_cm,omitempty"`
	Segments     json.RawMessage `json:"segments_px"`
	Error        string          `json:"error"`
}

// estimateResponse adalah kontrak ke client (PWA). Stateless: tidak ada yang ditulis ke DB.
type estimateResponse struct {
	Success        bool            `json:"success"`
	Method         string          `json:"method,omitempty"`
	MethodName     string          `json:"method_name,omitempty"`
	LengthCM       float64         `json:"length_cm,omitempty"`
	Confidence     float64         `json:"confidence,omitempty"`
	PPM            float64         `json:"ppm,omitempty"`
	MaxDimCM       float64         `json:"max_dim_cm,omitempty"`
	MarkerID       *int            `json:"marker_id,omitempty"`
	MarkerSidePX   *float64        `json:"marker_side_px,omitempty"`
	MarkerSizeCM   *float64        `json:"marker_size_cm,omitempty"`
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

	method := r.FormValue("method")
	if method == "" {
		method = r.URL.Query().Get("method")
	}
	if method == "" {
		method = "mediapipe"
	}
	if method != "mediapipe" && method != "contour_caliper" && method != "aruco_marker" {
		writeEstimate(w, http.StatusBadRequest, estimateResponse{
			Error: "method harus 'mediapipe', 'contour_caliper', atau 'aruco_marker'",
		})
		return
	}

	markerSize := 10.0
	if v := r.FormValue("marker_size_cm"); v != "" {
		if parsed, err := strconv.ParseFloat(v, 64); err == nil && parsed >= 1.0 && parsed <= 50.0 {
			markerSize = parsed
		}
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

	cmdArgs := []string{
		"estimate_length.py",
		"--image", inPath,
		"--method", method,
		"--max-dim-cm", strconv.FormatFloat(maxDim, 'f', 2, 64),
		"--marker-size-cm", strconv.FormatFloat(markerSize, 'f', 2, 64),
		"--output-annotated", outPath,
	}
	cmd := exec.CommandContext(ctx, pythonBin, cmdArgs...)
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
		writeEstimate(w, http.StatusBadGateway, estimateResponse{Error: "Estimator tidak tersedia di server (python/mediapipe/opencv belum terpasang?)"})
		return
	}

	if !res.Success {
		msg := res.Error
		if msg == "" {
			msg = "Estimasi gagal"
		}
		writeEstimate(w, http.StatusUnprocessableEntity, estimateResponse{
			Error:      msg,
			Method:     method,
			MethodName: res.MethodName,
			MaxDimCM:   maxDim,
		})
		return
	}

	resp := estimateResponse{
		Success:       true,
		Method:        res.Method,
		MethodName:    res.MethodName,
		LengthCM:      res.LengthCM,
		Confidence:    res.Confidence,
		PPM:           res.PPM,
		MaxDimCM:      maxDim,
		MarkerID:      res.MarkerID,
		MarkerSidePX:  res.MarkerSidePX,
		MarkerSizeCM:  res.MarkerSizeCM,
		Segments:      res.Segments,
		Plausible:     res.LengthCM >= plausibleMinLengthCM && res.LengthCM <= plausibleMaxLengthCM,
		LowConfidence: res.Confidence < estimateLowConfBelow,
	}
	if img, err := os.ReadFile(outPath); err == nil {
		resp.AnnotatedImage = "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(img)
	}
	writeEstimate(w, http.StatusOK, resp)
}
