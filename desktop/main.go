package main

import (
	"archive/zip"
	"bufio"
	"bytes"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

//go:embed payload.zip
var assets embed.FS

const pythonURL = "https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.zip"
const pythonSHA = "6479223746cdfb79d25865110d6f524ac98de081324e119af1dc3ae36bddc7a5"

var mu sync.Mutex
var status = map[string]any{"message": "Preparando IA Cuantitativa…", "progress": 0, "ready": "", "error": ""}

func update(message string, progress int) {
	mu.Lock()
	status["message"] = message
	status["progress"] = progress
	mu.Unlock()
}
func failure(err error) {
	mu.Lock()
	status["error"] = "No se pudo iniciar: " + err.Error() + ". Cerrá esta ventana y volvé a abrir la aplicación para reintentar."
	mu.Unlock()
}

const page = `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IA Cuantitativa</title><style>body{background:#f4f7ef;color:#234831;font:15px/1.7 system-ui;max-width:620px;margin:12vh auto;padding:25px}h1{font:42px Georgia}small{color:#6d7f64}progress{width:100%;accent-color:#386846}#error{color:#923d2c;white-space:pre-wrap}.mark{font:48px Georgia;border:1px solid #8ca17e;border-radius:15px;width:70px;text-align:center}button{padding:10px 16px;border-radius:6px;border:1px solid #bacbad;background:#fff;color:#234831;cursor:pointer}</style><div class="mark">iq</div><h1>Tu asistente, en este equipo.</h1><p id="message">Preparando IA Cuantitativa…</p><progress id="progress" max="100" value="0"></progress><p id="error"></p><small>En el primer inicio se descarga un entorno privado verificado desde python.org. No necesitás instalar Python ni abrir una terminal.</small><script src="/boot.js"></script></html>`
const script = `async function check(){try{const r=await fetch('/status');const s=await r.json();document.getElementById('message').textContent=s.message;document.getElementById('progress').value=s.progress;document.getElementById('error').textContent=s.error;if(s.ready){location.replace(s.ready);return;}if(s.error)return;}catch(e){}setTimeout(check,700)}check();`

func safeUnzip(raw []byte, destination string) error {
	z, err := zip.NewReader(bytes.NewReader(raw), int64(len(raw)))
	if err != nil {
		return err
	}
	root, err := filepath.Abs(destination)
	if err != nil {
		return err
	}
	if err = os.MkdirAll(root, 0700); err != nil {
		return err
	}
	var total uint64
	for _, f := range z.File {
		total += f.UncompressedSize64
		if total > 800*1024*1024 {
			return fmt.Errorf("el paquete expandido supera el límite")
		}
		name := strings.ReplaceAll(f.Name, "\\", "/")
		path := filepath.Join(root, filepath.FromSlash(name))
		rel, e := filepath.Rel(root, path)
		if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) || filepath.IsAbs(name) || f.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("ruta inválida en el paquete")
		}
		if f.FileInfo().IsDir() {
			if err = os.MkdirAll(path, 0700); err != nil {
				return err
			}
			continue
		}
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return err
		}
		input, e := f.Open()
		if e != nil {
			return e
		}
		output, e := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
		if e != nil {
			input.Close()
			return e
		}
		_, e = io.Copy(output, input)
		input.Close()
		output.Close()
		if e != nil {
			return e
		}
	}
	return nil
}
func installPython(root string) (string, error) {
	if override := os.Getenv("IQ_RUNTIME_PYTHON"); override != "" {
		return override, nil
	}
	folder := filepath.Join(root, "runtime-3.13.15")
	exe := filepath.Join(folder, "python.exe")
	if marker, e := os.ReadFile(filepath.Join(folder, "verified.sha256")); e == nil && string(marker) == pythonSHA {
		if _, e = os.Stat(exe); e == nil {
			return exe, nil
		}
	}
	update("Descargando el entorno privado…", 5)
	client := &http.Client{Timeout: 10 * time.Minute}
	response, e := client.Get(pythonURL)
	if e != nil {
		return "", fmt.Errorf("no se pudo descargar el entorno. Comprobá tu conexión")
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return "", fmt.Errorf("el distribuidor respondió HTTP %d", response.StatusCode)
	}
	var data bytes.Buffer
	hash := sha256.New()
	buf := make([]byte, 256*1024)
	var count int64
	for {
		n, err := response.Body.Read(buf)
		if n > 0 {
			count += int64(n)
			if count > 200*1024*1024 {
				return "", fmt.Errorf("descarga demasiado grande")
			}
			data.Write(buf[:n])
			hash.Write(buf[:n])
			if response.ContentLength > 0 {
				update("Descargando el entorno privado…", 5+int(70*count/response.ContentLength))
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", fmt.Errorf("se interrumpió la descarga")
		}
	}
	if hex.EncodeToString(hash.Sum(nil)) != pythonSHA {
		return "", fmt.Errorf("la descarga no superó la verificación de integridad")
	}
	update("Instalando el entorno privado…", 80)
	stage := folder + ".staging"
	os.RemoveAll(stage)
	if e = safeUnzip(data.Bytes(), stage); e != nil {
		return "", e
	}
	if _, e = os.Stat(filepath.Join(stage, "python.exe")); e != nil {
		return "", fmt.Errorf("el paquete no contiene el entorno esperado")
	}
	os.RemoveAll(folder)
	if e = os.Rename(stage, folder); e != nil {
		return "", e
	}
	if e = os.WriteFile(filepath.Join(folder, "verified.sha256"), []byte(pythonSHA), 0600); e != nil {
		return "", e
	}
	return exe, nil
}
func installedApp(root string) (string, error) {
	raw, e := assets.ReadFile("payload.zip")
	if e != nil {
		return "", e
	}
	sum := sha256.Sum256(raw)
	build := hex.EncodeToString(sum[:])[:12]
	folder := filepath.Join(root, "app-"+build)
	if _, e = os.Stat(filepath.Join(folder, "ready")); e == nil {
		return folder, nil
	}
	stage := folder + ".staging"
	os.RemoveAll(stage)
	if e = safeUnzip(raw, stage); e != nil {
		return "", e
	}
	if e = os.WriteFile(filepath.Join(stage, "ready"), []byte(build), 0600); e != nil {
		return "", e
	}
	os.RemoveAll(folder)
	if e = os.Rename(stage, folder); e != nil {
		return "", e
	}
	return folder, nil
}
func existing(root string) string {
	raw, e := os.ReadFile(filepath.Join(root, "running.json"))
	if e != nil {
		return ""
	}
	var data map[string]string
	if json.Unmarshal(raw, &data) != nil {
		return ""
	}
	address := data["url"]
	u, e := url.Parse(address)
	if e != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.Path != "" || u.User != nil {
		return ""
	}
	client := http.Client{Timeout: 2 * time.Second}
	r, e := client.Get(address + "/api/health")
	if e != nil {
		return ""
	}
	defer r.Body.Close()
	var health map[string]string
	if json.NewDecoder(io.LimitReader(r.Body, 2000)).Decode(&health) == nil && health["application"] == "ia-cuantitativa" {
		return address
	}
	return ""
}
func run(root string) error {
	python, e := installPython(root)
	if e != nil {
		return e
	}
	update("Preparando la aplicación…", 90)
	app, e := installedApp(root)
	if e != nil {
		return e
	}
	log, e := os.OpenFile(filepath.Join(root, "application.log"), os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	defer log.Close()
	command := exec.Command(python, "-I", filepath.Join(app, "run.py"), "--no-browser", "--port", "0", "--data-dir", filepath.Join(root, "data"))
	command.Dir = app
	hideWindow(command)
	command.Stderr = log
	stdout, e := command.StdoutPipe()
	if e != nil {
		return e
	}
	if e = command.Start(); e != nil {
		return e
	}
	scanner := bufio.NewScanner(stdout)
	started := false
	for scanner.Scan() {
		line := scanner.Text()
		fmt.Fprintln(log, line)
		index := strings.Index(line, "http://127.0.0.1:")
		if index >= 0 && !started {
			address := strings.TrimSpace(line[index:])
			u, e := url.Parse(address)
			if e != nil || u.Hostname() != "127.0.0.1" {
				continue
			}
			record, _ := json.Marshal(map[string]string{"url": address})
			if e = os.WriteFile(filepath.Join(root, "running.json"), record, 0600); e != nil {
				command.Process.Kill()
				return e
			}
			mu.Lock()
			status["ready"] = address
			status["progress"] = 100
			mu.Unlock()
			started = true
		}
	}
	e = command.Wait()
	os.Remove(filepath.Join(root, "running.json"))
	if !started {
		return fmt.Errorf("la aplicación no inició; el registro está en %s", filepath.Join(root, "application.log"))
	}
	return e
}
func main() {
	root, e := os.UserCacheDir()
	if e != nil {
		fatalMessage(e.Error())
		return
	}
	root = filepath.Join(root, "IA-Cuantitativa")
	if e = os.MkdirAll(root, 0700); e != nil {
		fatalMessage(e.Error())
		return
	}
	if address := existing(root); address != "" {
		openBrowser(address)
		return
	}
	listener, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		fatalMessage(e.Error())
		return
	}
	address := "http://" + listener.Addr().String()
	unlock, ok := instanceLock(root)
	if !ok {
		fatalMessage("IA Cuantitativa ya se está preparando. Esperá a que termine y volvé a abrirla.")
		return
	}
	defer unlock()
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.Host != listener.Addr().String() {
			http.Error(w, "Host no permitido", 403)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		switch r.URL.Path {
		case "/":
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			io.WriteString(w, page)
		case "/boot.js":
			w.Header().Set("Content-Type", "text/javascript")
			io.WriteString(w, script)
		case "/status":
			w.Header().Set("Content-Type", "application/json")
			mu.Lock()
			defer mu.Unlock()
			json.NewEncoder(w).Encode(status)
		default:
			http.NotFound(w, r)
		}
	})
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 15 * time.Second}
	go server.Serve(listener)
	openBrowser(address)
	if e = run(root); e != nil {
		failure(e)
		time.Sleep(5 * time.Second)
	}
	server.Close()
}
