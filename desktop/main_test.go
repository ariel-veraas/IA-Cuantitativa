package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestUnzipRejectsTraversal(t *testing.T) {
	var b bytes.Buffer
	w := zip.NewWriter(&b)
	f, _ := w.Create("../outside.txt")
	f.Write([]byte("bad"))
	w.Close()
	if safeUnzip(b.Bytes(), t.TempDir()) == nil {
		t.Fatal("unsafe path accepted")
	}
}
func TestUnzipPreservesFiles(t *testing.T) {
	var b bytes.Buffer
	w := zip.NewWriter(&b)
	f, _ := w.Create("iq/a.txt")
	f.Write([]byte("ok"))
	w.Close()
	dir := t.TempDir()
	if e := safeUnzip(b.Bytes(), dir); e != nil {
		t.Fatal(e)
	}
	raw, e := os.ReadFile(filepath.Join(dir, "iq/a.txt"))
	if e != nil || string(raw) != "ok" {
		t.Fatal("file missing")
	}
}
func TestExistingRejectsExternalAddress(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "running.json"), []byte(`{"url":"https://example.com"}`), 0600)
	if existing(dir) != "" {
		t.Fatal("external URL accepted")
	}
}
