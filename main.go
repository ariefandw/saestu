package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// Measurement represents baby weight and length data
type Measurement struct {
	ID          int64     `json:"id"`
	DeviceID    string    `json:"device_id"`
	WeightGrams float64   `json:"weight_grams"`
	LengthCM    float64   `json:"length_cm"`
	PhotoURL    string    `json:"photo_url,omitempty"`
	Notes       string    `json:"notes,omitempty"`
	CreatedAt   time.Time `json:"created_at"`
}

// IngestionPayload is for JSON POST
type IngestionPayload struct {
	DeviceID    string  `json:"device_id"`
	WeightGrams float64 `json:"weight_grams"`
	LengthCM    float64 `json:"length_cm"`
	Notes       string  `json:"notes"`
}

// LiveTelemetry for high-frequency non-blocking stream
type LiveTelemetry struct {
	DeviceID    string    `json:"device_id"`
	WeightGrams float64   `json:"weight_grams"`
	LengthCM    float64   `json:"length_cm"`
	IsStable    bool      `json:"is_stable"`
	Timestamp   time.Time `json:"timestamp"`
}

// SSEMessage envelope
type SSEMessage struct {
	Type string `json:"type"` // "live_telemetry" | "new_measurement" | "photo_updated"
	Data any    `json:"data"`
}

// SSE Broker for real-time updates
type SSEBroker struct {
	clients    map[chan []byte]bool
	newClients chan chan []byte
	defClients chan chan []byte
	broadcast  chan []byte
	mu         sync.Mutex
}

func newSSEBroker() *SSEBroker {
	b := &SSEBroker{
		clients:    make(map[chan []byte]bool),
		newClients: make(chan chan []byte),
		defClients: make(chan chan []byte),
		broadcast:  make(chan []byte, 100),
	}
	go b.listen()
	return b
}

func (b *SSEBroker) listen() {
	for {
		select {
		case s := <-b.newClients:
			b.mu.Lock()
			b.clients[s] = true
			b.mu.Unlock()
		case s := <-b.defClients:
			b.mu.Lock()
			if _, ok := b.clients[s]; ok {
				delete(b.clients, s)
				close(s)
			}
			b.mu.Unlock()
		case msg := <-b.broadcast:
			b.mu.Lock()
			for s := range b.clients {
				select {
				case s <- msg:
				default:
					// Drop if buffer full
				}
			}
			b.mu.Unlock()
		}
	}
}

func (b *SSEBroker) send(msgType string, data any) {
	msg := SSEMessage{
		Type: msgType,
		Data: data,
	}
	bytes, err := json.Marshal(msg)
	if err == nil {
		b.broadcast <- bytes
	}
}

// App context
type App struct {
	db     *sql.DB
	broker *SSEBroker
	upload string
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	uploadDir := "./uploads"
	if err := os.MkdirAll(uploadDir, 0755); err != nil {
		log.Fatalf("Failed to create upload dir: %v", err)
	}

	db, err := sql.Open("sqlite", "saestu_iot.db")
	if err != nil {
		log.Fatalf("Failed to open db: %v", err)
	}
	defer db.Close()

	if err := initDB(db); err != nil {
		log.Fatalf("Failed to init db schema: %v", err)
	}

	app := &App{
		db:     db,
		broker: newSSEBroker(),
		upload: uploadDir,
	}

	mux := http.NewServeMux()

	// 1. Live Telemetry Stream (High Frequency, In-Memory -> SSE)
	mux.HandleFunc("POST /api/v1/telemetry/live", app.handleLiveTelemetry)

	// 2. Commit Final Measurement (Saved to SQLite DB)
	mux.HandleFunc("POST /api/v1/measurements", app.handleJSONIngest)
	mux.HandleFunc("POST /api/v1/measurements/with-photo", app.handleMultipartIngest)

	// 3. Async Photo Upload (Jepret terpisah, di-link ke measurement terbaru)
	mux.HandleFunc("POST /api/v1/photos/upload", app.handleAsyncPhotoUpload)

	// 4. Query & Dashboard
	mux.HandleFunc("GET /api/v1/measurements", app.handleListMeasurements)
	mux.HandleFunc("GET /api/v1/events", app.handleSSE)

	// Static, Dashboard & Interactive Docs
	mux.Handle("GET /uploads/", http.StripPrefix("/uploads/", http.FileServer(http.Dir(uploadDir))))
	mux.HandleFunc("GET /{$}", app.handleDashboard)
	mux.HandleFunc("GET /docs", app.handleDocs)

	addr := ":" + port
	log.Printf("==================================================")
	log.Printf("👶 Saestu IoT Baby Scale Server v2.0 running on http://localhost%s", addr)
	log.Printf("📊 Live Dashboard: http://localhost%s", addr)
	log.Printf("📖 Panduan API   : http://localhost%s/docs", addr)
	log.Printf("⚡ Live Telemetry: POST http://localhost%s/api/v1/telemetry/live", addr)
	log.Printf("💾 Measurement Commit: POST http://localhost%s/api/v1/measurements", addr)
	log.Printf("📸 Async Photo Upload: POST http://localhost%s/api/v1/photos/upload", addr)
	log.Printf("==================================================")

	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("Server stopped: %v", err)
	}
}

func initDB(db *sql.DB) error {
	query := `
	CREATE TABLE IF NOT EXISTS measurements (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		device_id TEXT NOT NULL,
		weight_grams REAL NOT NULL,
		length_cm REAL NOT NULL DEFAULT 0.0,
		photo_url TEXT,
		notes TEXT,
		created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
	);
	CREATE INDEX IF NOT EXISTS idx_measurements_created_at ON measurements(created_at DESC);
	`
	_, err := db.Exec(query)
	return err
}

// 1. Handle Real-Time Live Telemetry (Zero DB Write, Immediate SSE Broadcast)
func (app *App) handleLiveTelemetry(w http.ResponseWriter, r *http.Request) {
	var t LiveTelemetry
	if err := json.NewDecoder(r.Body).Decode(&t); err != nil {
		http.Error(w, `{"error":"Invalid JSON"}`, http.StatusBadRequest)
		return
	}
	if t.DeviceID == "" {
		t.DeviceID = "ESP32-SCALE"
	}
	t.Timestamp = time.Now().UTC()

	app.broker.send("live_telemetry", t)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ok"}`))
}

// 2. Handle Committed Measurement (Written to SQLite DB)
func (app *App) handleJSONIngest(w http.ResponseWriter, r *http.Request) {
	var payload IngestionPayload
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, `{"error":"Invalid JSON payload"}`, http.StatusBadRequest)
		return
	}

	if payload.DeviceID == "" {
		payload.DeviceID = "ESP32-SCALE"
	}

	if payload.WeightGrams <= 0 {
		http.Error(w, `{"error":"Weight must be greater than 0"}`, http.StatusUnprocessableEntity)
		return
	}

	now := time.Now().UTC()
	res, err := app.db.Exec(
		`INSERT INTO measurements (device_id, weight_grams, length_cm, notes, created_at) VALUES (?, ?, ?, ?, ?)`,
		payload.DeviceID, payload.WeightGrams, payload.LengthCM, payload.Notes, now,
	)
	if err != nil {
		log.Printf("DB error: %v", err)
		http.Error(w, `{"error":"Database error"}`, http.StatusInternalServerError)
		return
	}

	id, _ := res.LastInsertId()
	m := Measurement{
		ID:          id,
		DeviceID:    payload.DeviceID,
		WeightGrams: payload.WeightGrams,
		LengthCM:    payload.LengthCM,
		Notes:       payload.Notes,
		CreatedAt:   now,
	}

	app.broker.send("new_measurement", m)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]any{
		"status":  "success",
		"message": "Measurement recorded",
		"data":    m,
	})
}

// 3. Handle Async Photo Upload (Jepret Asinkron dari ESP32-CAM)
func (app *App) handleAsyncPhotoUpload(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(10 << 20); err != nil {
		http.Error(w, `{"error":"File too large or malformed"}`, http.StatusBadRequest)
		return
	}

	deviceID := r.FormValue("device_id")
	if deviceID == "" {
		deviceID = "ESP32-CAM-01"
	}

	file, header, err := r.FormFile("photo")
	if err != nil {
		http.Error(w, `{"error":"Photo file is required"}`, http.StatusBadRequest)
		return
	}
	defer file.Close()

	ext := filepath.Ext(header.Filename)
	if ext == "" {
		ext = ".jpg"
	}
	filename := fmt.Sprintf("cam_%d_%s%s", time.Now().UnixNano(), deviceID, ext)
	dstPath := filepath.Join(app.upload, filename)

	dst, err := os.Create(dstPath)
	if err != nil {
		http.Error(w, `{"error":"Failed saving photo"}`, http.StatusInternalServerError)
		return
	}
	defer dst.Close()

	if _, err := io.Copy(dst, file); err != nil {
		http.Error(w, `{"error":"Failed saving photo content"}`, http.StatusInternalServerError)
		return
	}

	photoURL := "/uploads/" + filename

	// Cari measurement terakhir untuk di-link
	var targetID int64
	measurementIDStr := r.FormValue("measurement_id")
	if measurementIDStr != "" {
		targetID, _ = strconv.ParseInt(measurementIDStr, 10, 64)
	}

	if targetID == 0 {
		// Auto-link ke data timbangan paling baru (maksimal 10 menit terakhir)
		err = app.db.QueryRow(`
			SELECT id FROM measurements 
			WHERE (photo_url IS NULL OR photo_url = '') 
			ORDER BY created_at DESC LIMIT 1
		`).Scan(&targetID)
	}

	if targetID > 0 {
		app.db.Exec(`UPDATE measurements SET photo_url = ? WHERE id = ?`, photoURL, targetID)
	}

	app.broker.send("photo_updated", map[string]any{
		"measurement_id": targetID,
		"photo_url":       photoURL,
		"device_id":       deviceID,
	})

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]any{
		"status":         "success",
		"photo_url":      photoURL,
		"measurement_id": targetID,
		"message":        "Photo uploaded and linked asynchronously",
	})
}

// 4. Synchronous Combined Upload (Fallback)
func (app *App) handleMultipartIngest(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(10 << 20); err != nil {
		http.Error(w, `{"error":"File too large or malformed"}`, http.StatusBadRequest)
		return
	}

	deviceID := r.FormValue("device_id")
	if deviceID == "" {
		deviceID = "ESP32-CAM-UNKNOWN"
	}

	weightStr := r.FormValue("weight_grams")
	weight, err := strconv.ParseFloat(weightStr, 64)
	if err != nil || weight <= 0 {
		http.Error(w, `{"error":"Valid weight_grams is required"}`, http.StatusUnprocessableEntity)
		return
	}

	lengthStr := r.FormValue("length_cm")
	length, _ := strconv.ParseFloat(lengthStr, 64)
	notes := r.FormValue("notes")

	var photoURL string
	file, header, err := r.FormFile("photo")
	if err == nil {
		defer file.Close()
		ext := filepath.Ext(header.Filename)
		if ext == "" {
			ext = ".jpg"
		}
		filename := fmt.Sprintf("snap_%d_%d%s", time.Now().UnixNano(), int64(weight), ext)
		dstPath := filepath.Join(app.upload, filename)

		dst, err := os.Create(dstPath)
		if err != nil {
			http.Error(w, `{"error":"Failed saving photo"}`, http.StatusInternalServerError)
			return
		}
		defer dst.Close()

		if _, err := io.Copy(dst, file); err != nil {
			http.Error(w, `{"error":"Failed saving photo content"}`, http.StatusInternalServerError)
			return
		}

		photoURL = "/uploads/" + filename
	}

	now := time.Now().UTC()
	res, err := app.db.Exec(
		`INSERT INTO measurements (device_id, weight_grams, length_cm, photo_url, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)`,
		deviceID, weight, length, photoURL, notes, now,
	)
	if err != nil {
		log.Printf("DB error: %v", err)
		http.Error(w, `{"error":"Database error"}`, http.StatusInternalServerError)
		return
	}

	id, _ := res.LastInsertId()
	m := Measurement{
		ID:          id,
		DeviceID:    deviceID,
		WeightGrams: weight,
		LengthCM:    length,
		PhotoURL:    photoURL,
		Notes:       notes,
		CreatedAt:   now,
	}

	app.broker.send("new_measurement", m)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(map[string]any{
		"status":  "success",
		"message": "Measurement and photo recorded",
		"data":    m,
	})
}

func (app *App) handleListMeasurements(w http.ResponseWriter, r *http.Request) {
	limitStr := r.URL.Query().Get("limit")
	limit := 50
	if l, err := strconv.Atoi(limitStr); err == nil && l > 0 && l <= 500 {
		limit = l
	}

	rows, err := app.db.Query(
		`SELECT id, device_id, weight_grams, length_cm, COALESCE(photo_url, ''), COALESCE(notes, ''), created_at 
		 FROM measurements ORDER BY created_at DESC LIMIT ?`,
		limit,
	)
	if err != nil {
		log.Printf("DB query error: %v", err)
		http.Error(w, `{"error":"Database error"}`, http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	list := make([]Measurement, 0)
	for rows.Next() {
		var m Measurement
		if err := rows.Scan(&m.ID, &m.DeviceID, &m.WeightGrams, &m.LengthCM, &m.PhotoURL, &m.Notes, &m.CreatedAt); err != nil {
			log.Printf("Scan error: %v", err)
			continue
		}
		list = append(list, m)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(list)
}

func (app *App) handleSSE(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "Streaming unsupported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	messageChan := make(chan []byte, 10)
	app.broker.newClients <- messageChan

	defer func() {
		app.broker.defClients <- messageChan
	}()

	notify := r.Context().Done()

	for {
		select {
		case <-notify:
			return
		case msg := <-messageChan:
			fmt.Fprintf(w, "data: %s\n\n", msg)
			flusher.Flush()
		}
	}
}

func (app *App) handleDashboard(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(dashboardHTML))
}

func (app *App) handleDocs(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(docsHTML))
}

const dashboardHTML = `<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Saestu Scale</title>
  <script>
    if (localStorage.theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  </script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'selector',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', -apple-system, 'BlinkMacSystemFont', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          }
        }
      }
    };
  </script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-body: #fafafa;
      --text-body: #18181b;
      --bg-header: rgba(255, 255, 255, 0.85);
      --border-header: #e4e4e7;
      --bg-card: #ffffff;
      --border-card: #e4e4e7;
      --bg-subtle: #f4f4f5;
      --text-muted: #71717a;
      --border-row: #f4f4f5;
      --hover-row: #f4f4f5;
      --border-divider: #e4e4e7;
    }
    html.dark {
      --bg-body: #09090b;
      --text-body: #f4f4f5;
      --bg-header: rgba(9, 9, 11, 0.85);
      --border-header: #18181b;
      --bg-card: rgba(24, 24, 27, 0.4);
      --border-card: rgba(39, 39, 42, 0.8);
      --bg-subtle: rgba(9, 9, 11, 0.6);
      --text-muted: #a1a1aa;
      --border-row: rgba(39, 39, 42, 0.4);
      --hover-row: rgba(39, 39, 42, 0.3);
      --border-divider: rgba(39, 39, 42, 0.8);
    }
    body { 
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; 
      background-color: var(--bg-body);
      color: var(--text-body);
      transition: background-color 0.15s ease, color 0.15s ease;
    }
    .mono { font-family: 'JetBrains Mono', monospace; }
    .theme-header { background-color: var(--bg-header); border-color: var(--border-header); }
    .theme-card { background-color: var(--bg-card); border-color: var(--border-card); }
    .theme-subtle { background-color: var(--bg-subtle); border-color: var(--border-card); }
    .theme-divider { border-color: var(--border-divider); }
    .theme-row { border-color: var(--border-row); }
    .theme-row:hover { background-color: var(--hover-row); }
    .theme-muted { color: var(--text-muted); }
    .theme-link { color: var(--text-muted); transition: color 0.15s ease; }
    .theme-link:hover { color: var(--text-body); }
    .theme-btn { color: var(--text-muted); transition: all 0.15s ease; }
    .theme-btn:hover { color: var(--text-body); background-color: var(--hover-row); }
  </style>
</head>
<body class="min-h-screen antialiased">

  <!-- Header -->
  <header class="border-b theme-header backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <span class="font-semibold text-sm tracking-tight">Saestu Scale</span>
      </div>

      <div class="flex items-center space-x-4 text-xs">
        <span id="status-text" class="theme-muted mono">Connecting...</span>
        
        <!-- Dark/Light Mode Toggle Button -->
        <button onclick="toggleTheme()" class="p-1.5 rounded-lg theme-btn flex items-center justify-center w-8 h-8" title="Ganti Tema">
          <span id="theme-icon"></span>
        </button>

        <a href="/docs" class="flex items-center gap-1 theme-link">
          <span>API Docs</span>
          <i data-lucide="chevron-right" class="w-3.5 h-3.5"></i>
        </a>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-6 py-8 space-y-6">
    
    <!-- Live Scale Card (Berat, Tinggi, Foto Kamera in 1 Row + Catatan Full Width) -->
    <div class="theme-card border rounded-2xl p-6 sm:p-8 shadow-sm dark:shadow-none space-y-6">
      
      <!-- Top Status Row -->
      <div class="flex items-center justify-between text-xs">
        <div class="flex items-center space-x-2">
          <span id="badge-stable" class="px-2.5 py-1 rounded-md bg-zinc-800 text-white dark:bg-zinc-700 dark:text-zinc-100 border border-zinc-700 dark:border-zinc-600 mono font-semibold tracking-wide">Standby</span>
          <span class="theme-muted mono" id="live-device-id">Device: --</span>
        </div>
        <span class="theme-muted mono" id="live-timestamp">--</span>
      </div>

      <!-- 1 Row Grid: Berat Badan, Tinggi Badan, Foto Kamera -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6 items-center">
        
        <!-- 1. Berat Badan -->
        <div>
          <div class="text-xs theme-muted uppercase tracking-wider mb-1">Berat Badan</div>
          <div class="flex items-baseline space-x-3">
            <span class="text-5xl sm:text-6xl font-bold mono tracking-tight" id="live-weight">0.00</span>
            <span class="text-xl font-medium theme-muted mono">kg</span>
            <span class="text-sm theme-muted mono" id="live-weight-grams">(0 g)</span>
          </div>
        </div>

        <!-- 2. Tinggi Badan -->
        <div class="md:border-l theme-divider md:pl-6">
          <div class="text-xs theme-muted uppercase tracking-wider mb-1">Tinggi Badan</div>
          <div class="flex items-baseline space-x-2">
            <span class="text-4xl sm:text-5xl font-semibold mono" id="live-length">--</span>
            <span class="text-sm theme-muted mono">cm</span>
          </div>
        </div>

        <!-- 3. Foto Kamera -->
        <div class="md:border-l theme-divider md:pl-6 flex flex-col items-start gap-2">
          <div onclick="openPhotoModalFromHero()" class="w-28 h-28 sm:w-32 sm:h-32 theme-subtle border rounded-xl overflow-hidden flex items-center justify-center flex-shrink-0 cursor-pointer group relative hover:opacity-90 transition shadow-sm" title="Klik untuk memperbesar foto">
            <img id="latest-photo" src="" alt="Snapshot" class="hidden w-full h-full object-cover transition-transform duration-200 group-hover:scale-105" onerror="this.classList.add('hidden'); document.getElementById('photo-placeholder').classList.remove('hidden');" />
            <div id="photo-placeholder" class="text-xs theme-muted flex flex-col items-center gap-1.5 text-center p-2">
              <i data-lucide="image" class="w-6 h-6 stroke-1"></i>
              <span class="text-xs">Foto</span>
            </div>
            <!-- Zoom Icon Overlay -->
            <div id="photo-zoom-badge" class="hidden absolute bottom-1.5 right-1.5 bg-black/60 text-white rounded-md p-1 group-hover:bg-black/80 transition backdrop-blur">
              <i data-lucide="zoom-in" class="w-3.5 h-3.5"></i>
            </div>
          </div>
          <div class="flex items-baseline gap-2 text-xs">
            <span class="theme-muted uppercase tracking-wider text-[10px]">Snapshot Kamera</span>
            <span class="mono font-semibold" id="latest-linked-id">-</span>
          </div>
        </div>

      </div>

      <!-- Catatan Menguasai Satu Baris di Bawahnya -->
      <div class="pt-4 border-t theme-divider flex items-baseline gap-2 text-xs">
        <span class="theme-muted uppercase tracking-wider font-semibold text-[11px] flex-shrink-0">Catatan:</span>
        <span id="latest-notes" class="truncate">-</span>
      </div>

    </div>

    <!-- Chart (Full Width) -->
    <div class="theme-card border rounded-2xl p-6 shadow-sm dark:shadow-none">
      <div class="flex items-center justify-between mb-4">
        <span class="text-xs font-medium theme-muted">Riwayat Penimbangan</span>
        <span class="text-xs theme-muted mono" id="stat-total-count">0 Data</span>
      </div>
      <div class="relative h-64 w-full">
        <canvas id="weightChart"></canvas>
      </div>
    </div>

    <!-- Data Table -->
    <div class="theme-card border rounded-2xl p-6 space-y-4 shadow-sm dark:shadow-none">
      <div class="flex items-center justify-between">
        <span class="text-xs font-medium theme-muted">Log Penimbangan</span>
        <button onclick="fetchInitialData()" class="flex items-center gap-1.5 text-xs theme-link">
          <i data-lucide="rotate-cw" class="w-3 h-3"></i>
          <span>Refresh</span>
        </button>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b theme-divider theme-muted mono">
              <th class="py-2.5 px-3 font-normal">Waktu</th>
              <th class="py-2.5 px-3 font-normal">Device</th>
              <th class="py-2.5 px-3 font-normal">Berat</th>
              <th class="py-2.5 px-3 font-normal">Tinggi</th>
              <th class="py-2.5 px-3 font-normal">Foto</th>
              <th class="py-2.5 px-3 font-normal">Catatan</th>
            </tr>
          </thead>
          <tbody id="measurements-table" class="divide-y theme-divider mono">
            <tr>
              <td colspan="6" class="py-6 text-center theme-muted">Memuat data...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <!-- Photo Preview Modal Dialog -->
  <div id="photo-modal" class="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm hidden flex items-center justify-center p-4 transition-opacity" onclick="closePhotoModal(event)">
    <div class="theme-card border rounded-2xl max-w-2xl w-full overflow-hidden shadow-2xl space-y-0" onclick="event.stopPropagation()">
      <!-- Dialog Header -->
      <div class="px-5 py-3.5 border-b theme-divider flex items-center justify-between">
        <div class="flex items-center gap-2">
          <i data-lucide="camera" class="w-4 h-4 theme-muted"></i>
          <span id="modal-title" class="text-xs font-semibold mono tracking-tight">Foto Snapshot Kamera</span>
        </div>
        <button onclick="closePhotoModalDirect()" class="p-1 rounded-lg theme-btn" title="Tutup">
          <i data-lucide="x" class="w-4 h-4"></i>
        </button>
      </div>

      <!-- Dialog Body Image -->
      <div class="bg-zinc-950 flex items-center justify-center p-2 min-h-[300px] max-h-[70vh] overflow-hidden">
        <img id="modal-image" src="" alt="Snapshot Full" class="max-h-[68vh] w-auto max-w-full rounded-lg object-contain" />
      </div>

      <!-- Dialog Footer Details -->
      <div class="px-5 py-3 border-t theme-divider flex items-center justify-between text-xs theme-muted mono">
        <span id="modal-caption">-</span>
        <a id="modal-raw-link" href="" target="_blank" class="theme-link flex items-center gap-1 hover:underline">
          <span>Buka File Asli</span>
          <i data-lucide="external-link" class="w-3 h-3"></i>
        </a>
      </div>
    </div>
  </div>

  <script>
    let measurements = [];
    let chart = null;

    function isDarkMode() {
      return document.documentElement.classList.contains('dark');
    }

    function updateThemeIcon() {
      const container = document.getElementById('theme-icon');
      if (!container) return;
      container.innerHTML = isDarkMode() 
        ? '<i data-lucide="sun" class="w-4 h-4"></i>' 
        : '<i data-lucide="moon" class="w-4 h-4"></i>';
      lucide.createIcons({ root: container });
    }

    function toggleTheme() {
      if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
        localStorage.theme = 'light';
      } else {
        document.documentElement.classList.add('dark');
        localStorage.theme = 'dark';
      }
      updateThemeIcon();
      updateChartTheme();
    }

    function updateChartTheme() {
      if (!chart) return;
      const isDark = isDarkMode();
      chart.options.scales.x.ticks.color = isDark ? '#71717a' : '#a1a1aa';
      chart.options.scales.y.ticks.color = isDark ? '#71717a' : '#a1a1aa';
      chart.options.scales.y.grid.color = isDark ? '#27272a' : '#f4f4f5';
      chart.data.datasets[0].borderColor = isDark ? '#a1a1aa' : '#71717a';
      chart.data.datasets[0].pointBackgroundColor = isDark ? '#f4f4f5' : '#18181b';
      chart.data.datasets[0].pointBorderColor = isDark ? '#09090b' : '#ffffff';
      chart.update();
    }

    function initChart() {
      const ctx = document.getElementById('weightChart').getContext('2d');
      const isDark = isDarkMode();
      chart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: [],
          datasets: [{
            data: [],
            borderColor: isDark ? '#a1a1aa' : '#71717a',
            borderWidth: 1.5,
            backgroundColor: 'transparent',
            pointBackgroundColor: isDark ? '#f4f4f5' : '#18181b',
            pointBorderColor: isDark ? '#09090b' : '#ffffff',
            pointRadius: 3,
            pointHoverRadius: 5,
            tension: 0.2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: isDark ? '#18181b' : '#ffffff',
              borderColor: isDark ? '#27272a' : '#e4e4e7',
              borderWidth: 1,
              titleColor: isDark ? '#a1a1aa' : '#71717a',
              bodyColor: isDark ? '#f4f4f5' : '#09090b',
              callbacks: {
                label: (ctx) => ctx.parsed.y + ' g (' + (ctx.parsed.y / 1000).toFixed(2) + ' kg)'
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: isDark ? '#71717a' : '#a1a1aa', font: { family: 'JetBrains Mono', size: 10 } }
            },
            y: {
              grid: { color: isDark ? '#27272a' : '#f4f4f5' },
              ticks: { color: isDark ? '#71717a' : '#a1a1aa', font: { family: 'JetBrains Mono', size: 10 } }
            }
          }
        }
      });
    }

    function renderUI() {
      if (measurements.length === 0) return;

      const latest = measurements[0];
      document.getElementById('stat-total-count').textContent = measurements.length + ' Data';

      const photoEl = document.getElementById('latest-photo');
      const placeholderEl = document.getElementById('photo-placeholder');
      const zoomBadgeEl = document.getElementById('photo-zoom-badge');
      const linkedIdEl = document.getElementById('latest-linked-id');
      const notesEl = document.getElementById('latest-notes');

      const itemWithPhoto = measurements.find(m => m.photo_url && m.photo_url.trim() !== '');
      if (itemWithPhoto) {
        photoEl.src = itemWithPhoto.photo_url;
        photoEl.classList.remove('hidden');
        placeholderEl.classList.add('hidden');
        if (zoomBadgeEl) zoomBadgeEl.classList.remove('hidden');
        linkedIdEl.textContent = '#' + itemWithPhoto.id;
        notesEl.textContent = itemWithPhoto.notes || '-';
      } else {
        photoEl.classList.add('hidden');
        placeholderEl.classList.remove('hidden');
        if (zoomBadgeEl) zoomBadgeEl.classList.add('hidden');
        linkedIdEl.textContent = '-';
        notesEl.textContent = '-';
      }

      const tbody = document.getElementById('measurements-table');
      tbody.innerHTML = measurements.map(m => {
        const d = new Date(m.created_at);
        const timeStr = d.toLocaleDateString('id-ID', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
        const hasPhoto = m.photo_url && m.photo_url.trim() !== '';
        const notesEscaped = (m.notes || '').replace(/'/g, "\\'");
        const photoCell = hasPhoto 
          ? '<button onclick="openPhotoModal(\'' + m.photo_url + '\', \'#' + m.id + ' - ' + (m.weight_grams/1000).toFixed(2) + ' kg\', \'' + notesEscaped + '\')" class="theme-link inline-flex items-center gap-1 font-medium hover:underline underline-offset-2"><span>Lihat</span><i data-lucide="image" class="w-3.5 h-3.5"></i></button>' 
          : '<span class="theme-muted">Tidak ada</span>';
        
        return '<tr class="theme-row transition">' +
          '<td class="py-2.5 px-3 theme-muted">' + timeStr + '</td>' +
          '<td class="py-2.5 px-3 theme-muted">' + m.device_id + '</td>' +
          '<td class="py-2.5 px-3 font-medium">' + (m.weight_grams/1000).toFixed(2) + ' kg <span class="theme-muted font-normal">(' + m.weight_grams + ' g)</span></td>' +
          '<td class="py-2.5 px-3 theme-muted">' + (m.length_cm ? m.length_cm.toFixed(1) + ' cm' : '-') + '</td>' +
          '<td class="py-2.5 px-3">' + photoCell + '</td>' +
          '<td class="py-2.5 px-3 theme-muted">' + (m.notes || '-') + '</td>' +
        '</tr>';
      }).join('');

      const chartItems = [...measurements].slice(0, 15).reverse();
      chart.data.labels = chartItems.map(m => new Date(m.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }));
      chart.data.datasets[0].data = chartItems.map(m => m.weight_grams);
      chart.update();

      lucide.createIcons();
    }

    function handleLiveTelemetry(t) {
      document.getElementById('live-weight').textContent = (t.weight_grams / 1000).toFixed(2);
      document.getElementById('live-weight-grams').textContent = '(' + Math.round(t.weight_grams) + ' g)';
      if (t.length_cm > 0) {
        document.getElementById('live-length').textContent = t.length_cm.toFixed(1);
      }
      document.getElementById('live-device-id').textContent = 'Device: ' + t.device_id;
      document.getElementById('live-timestamp').textContent = new Date(t.timestamp || Date.now()).toLocaleTimeString('id-ID');

      const badge = document.getElementById('badge-stable');
      if (t.is_stable) {
        badge.className = 'px-2.5 py-1 rounded-md bg-emerald-600 text-white dark:bg-emerald-700 dark:text-emerald-50 border border-emerald-500 dark:border-emerald-600 mono font-semibold tracking-wide';
        badge.textContent = 'Stabil';
      } else {
        badge.className = 'px-2.5 py-1 rounded-md bg-zinc-800 text-white dark:bg-zinc-700 dark:text-zinc-100 border border-zinc-700 dark:border-zinc-600 mono font-semibold tracking-wide';
        badge.textContent = 'Menimbang';
      }
    }

    async function fetchInitialData() {
      try {
        const res = await fetch('/api/v1/measurements?limit=50');
        if (res.ok) {
          measurements = await res.json();
          renderUI();
        }
      } catch (err) {
        console.error(err);
      }
    }

    function initSSE() {
      const dot = document.getElementById('status-dot');
      const text = document.getElementById('status-text');
      const es = new EventSource('/api/v1/events');

      es.onopen = () => {
        dot.className = 'w-2 h-2 rounded-full bg-emerald-500';
        text.textContent = 'Live';
      };

      es.onmessage = (event) => {
        try {
          const envelope = JSON.parse(event.data);
          if (envelope.type === 'live_telemetry') {
            handleLiveTelemetry(envelope.data);
          } else if (envelope.type === 'new_measurement') {
            measurements.unshift(envelope.data);
            renderUI();
          } else if (envelope.type === 'photo_updated') {
            const target = measurements.find(m => m.id === envelope.data.measurement_id);
            if (target) target.photo_url = envelope.data.photo_url;
            renderUI();
          }
        } catch (e) {
          console.error(e);
        }
      };

      es.onerror = () => {
        dot.className = 'w-2 h-2 rounded-full bg-zinc-400 dark:bg-zinc-600';
        text.textContent = 'Offline';
      };
    }

    function openPhotoModal(url, title, caption) {
      if (!url || url.trim() === '') return;
      const modal = document.getElementById('photo-modal');
      const img = document.getElementById('modal-image');
      const titleEl = document.getElementById('modal-title');
      const captionEl = document.getElementById('modal-caption');
      const rawLinkEl = document.getElementById('modal-raw-link');

      img.src = url;
      titleEl.textContent = 'Snapshot ' + (title || 'Kamera');
      captionEl.textContent = caption || 'Tanpa catatan';
      rawLinkEl.href = url;

      modal.classList.remove('hidden');
      document.body.style.overflow = 'hidden';
      lucide.createIcons({ root: modal });
    }

    function openPhotoModalFromHero() {
      const itemWithPhoto = measurements.find(m => m.photo_url && m.photo_url.trim() !== '');
      if (itemWithPhoto) {
        openPhotoModal(itemWithPhoto.photo_url, '#' + itemWithPhoto.id + ' (' + (itemWithPhoto.weight_grams/1000).toFixed(2) + ' kg)', itemWithPhoto.notes);
      }
    }

    function closePhotoModalDirect() {
      const modal = document.getElementById('photo-modal');
      modal.classList.add('hidden');
      document.body.style.overflow = '';
    }

    function closePhotoModal(e) {
      if (e.target.id === 'photo-modal') {
        closePhotoModalDirect();
      }
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closePhotoModalDirect();
    });

    document.addEventListener('DOMContentLoaded', () => {
      updateThemeIcon();
      lucide.createIcons();
      initChart();
      fetchInitialData();
      initSSE();
    });
  </script>
</body>
</html>
`

const docsHTML = `<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>API Reference - Saestu Scale</title>
  <script>
    if (localStorage.theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  </script>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'selector',
      theme: {
        extend: {
          fontFamily: {
            sans: ['Inter', -apple-system, 'BlinkMacSystemFont', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
          }
        }
      }
    };
  </script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-body: #fafafa;
      --text-body: #18181b;
      --bg-header: rgba(255, 255, 255, 0.85);
      --border-header: #e4e4e7;
      --bg-card: #ffffff;
      --border-card: #e4e4e7;
      --text-muted: #71717a;
    }
    html.dark {
      --bg-body: #09090b;
      --text-body: #f4f4f5;
      --bg-header: rgba(9, 9, 11, 0.85);
      --border-header: #18181b;
      --bg-card: rgba(24, 24, 27, 0.4);
      --border-card: rgba(39, 39, 42, 0.8);
      --text-muted: #a1a1aa;
    }
    body { 
      font-family: 'Inter', sans-serif; 
      background-color: var(--bg-body);
      color: var(--text-body);
      transition: background-color 0.15s ease, color 0.15s ease;
    }
    .mono { font-family: 'JetBrains Mono', monospace; }
    .theme-header { background-color: var(--bg-header); border-color: var(--border-header); }
    .theme-card { background-color: var(--bg-card); border-color: var(--border-card); }
    .theme-divider { border-color: #e4e4e7; }
    html.dark .theme-divider { border-color: rgba(39, 39, 42, 0.8); }
    .theme-muted { color: var(--text-muted); }
    .theme-link { color: var(--text-muted); transition: color 0.15s ease; }
    .theme-link:hover { color: var(--text-body); }
    .theme-btn { color: var(--text-muted); transition: all 0.15s ease; }
    .theme-btn:hover { color: var(--text-body); background-color: #f4f4f5; }
    html.dark .theme-btn:hover { background-color: rgba(39, 39, 42, 0.3); }
  </style>
</head>
<body class="min-h-screen antialiased selection:bg-zinc-800 selection:text-white">

  <header class="border-b theme-header backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
      <div class="flex items-center space-x-3 text-sm">
        <a href="/" class="flex items-center gap-1 theme-link">
          <i data-lucide="chevron-left" class="w-4 h-4"></i>
          <span>Dashboard</span>
        </a>
        <span class="text-zinc-300 dark:text-zinc-700">/</span>
        <span class="font-medium">API Documentation</span>
      </div>

      <!-- Theme Switcher -->
      <button onclick="toggleTheme()" class="p-1.5 rounded-lg theme-btn flex items-center justify-center w-8 h-8" title="Ganti Tema">
        <span id="theme-icon"></span>
      </button>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-6 py-10 space-y-12 text-sm leading-relaxed">
    
    <!-- Header info -->
    <div>
      <h1 class="text-2xl font-bold tracking-tight mb-2">Integrasi Perangkat IoT</h1>
      <p class="theme-muted">Kontrak endpoint RESTful & script integrasi untuk Mini PC dan mikrokontroler.</p>
    </div>

    <!-- Section 1: Endpoints list -->
    <section class="space-y-4">
      <h2 class="text-xs font-semibold uppercase tracking-wider theme-muted">Daftar Endpoint</h2>
      
      <div class="border theme-card rounded-xl overflow-hidden divide-y theme-divider mono text-xs shadow-sm dark:shadow-none">
        <div class="p-3.5 flex items-baseline justify-between">
          <div><span class="text-emerald-600 dark:text-emerald-400 font-semibold mr-2">POST</span>/api/v1/telemetry/live</div>
          <span class="theme-muted font-sans text-[11px]">Live stream tiap 200ms (in-memory)</span>
        </div>
        <div class="p-3.5 flex items-baseline justify-between">
          <div><span class="text-emerald-600 dark:text-emerald-400 font-semibold mr-2">POST</span>/api/v1/measurements</div>
          <span class="theme-muted font-sans text-[11px]">Simpan hasil timbangan ke DB</span>
        </div>
        <div class="p-3.5 flex items-baseline justify-between">
          <div><span class="font-semibold mr-2">POST</span>/api/v1/photos/upload</div>
          <span class="theme-muted font-sans text-[11px]">Upload foto kamera Logitech</span>
        </div>
        <div class="p-3.5 flex items-baseline justify-between">
          <div><span class="theme-muted font-semibold mr-2">GET</span>/api/v1/events</div>
          <span class="theme-muted font-sans text-[11px]">SSE stream event</span>
        </div>
      </div>
    </section>

    <!-- Section 2: Mini PC -->
    <section class="space-y-4">
      <h2 class="text-xs font-semibold uppercase tracking-wider theme-muted">1. Mini PC + Kamera Logitech (Python)</h2>
      <p class="theme-muted text-xs">Install dependensi lalu jalankan script agent pengunggah foto:</p>
      
      <div class="theme-card border rounded-xl p-4 space-y-3 mono text-xs shadow-sm dark:shadow-none">
        <div class="theme-muted"># 1. Install library</div>
        <div class="font-medium">pip install opencv-python requests</div>
        
        <div class="theme-muted pt-2"># 2. Upload foto</div>
        <div class="font-medium">python minipc_camera_agent.py --server http://&lt;IP_SERVER&gt;:8080 --device MINIPC-01</div>
      </div>
    </section>

    <!-- Section 3: ESP32 -->
    <section class="space-y-4">
      <h2 class="text-xs font-semibold uppercase tracking-wider theme-muted">2. ESP32 Loadcell (C++ Arduino)</h2>
      <p class="theme-muted text-xs">Fungsi pengiriman data berat dari sensor HX711:</p>
      
      <pre class="theme-card border rounded-xl p-4 mono text-xs overflow-x-auto leading-relaxed shadow-sm dark:shadow-none">
// Kirim live data ke gauge dashboard
void sendLiveTelemetry(float weight, float length, bool isStable) {
  HTTPClient http;
  http.begin("http://&lt;IP_SERVER&gt;:8080/api/v1/telemetry/live");
  http.addHeader("Content-Type", "application/json");

  String body = "{\"device_id\":\"ESP32-01\",\"weight_grams\":" + String(weight) + ",\"is_stable\":" + (isStable ? "true" : "false") + "}";
  http.POST(body);
  http.end();
}

// Simpan permanen saat bobot stabil
void saveMeasurement(float weight, float length, const char* notes) {
  HTTPClient http;
  http.begin("http://&lt;IP_SERVER&gt;:8080/api/v1/measurements");
  http.addHeader("Content-Type", "application/json");

  String body = "{\"device_id\":\"ESP32-01\",\"weight_grams\":" + String(weight) + ",\"length_cm\":" + String(length) + ",\"notes\":\"" + String(notes) + "\"}";
  http.POST(body);
  http.end();
}</pre>
    </section>

  </main>

  <footer class="border-t border-zinc-200 dark:border-zinc-900 py-8 text-center text-xs theme-muted mono">
    Saestu Scale System
  </footer>

  <script>
    function isDarkMode() {
      return document.documentElement.classList.contains('dark');
    }

    function updateThemeIcon() {
      const container = document.getElementById('theme-icon');
      if (!container) return;
      container.innerHTML = isDarkMode() 
        ? '<i data-lucide="sun" class="w-4 h-4"></i>' 
        : '<i data-lucide="moon" class="w-4 h-4"></i>';
      lucide.createIcons({ root: container });
    }

    function toggleTheme() {
      if (document.documentElement.classList.contains('dark')) {
        document.documentElement.classList.remove('dark');
        localStorage.theme = 'light';
      } else {
        document.documentElement.classList.add('dark');
        localStorage.theme = 'dark';
      }
      updateThemeIcon();
    }

    document.addEventListener('DOMContentLoaded', () => {
      updateThemeIcon();
      lucide.createIcons();
    });
  </script>

</body>
</html>
`



