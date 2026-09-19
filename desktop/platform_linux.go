package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
)

func hideWindow(c *exec.Cmd) {}
func openBrowser(url string) {
	fmt.Println("OPEN", url)
	if os.Getenv("IQ_NO_BROWSER") != "1" {
		exec.Command("xdg-open", url).Start()
	}
}
func fatalMessage(message string) { fmt.Fprintln(os.Stderr, message) }
func instanceLock(root string) (func(), bool) {
	f, e := os.OpenFile(filepath.Join(root, "launcher.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return func() {}, false
	}
	if syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB) != nil {
		f.Close()
		return func() {}, false
	}
	return func() { syscall.Flock(int(f.Fd()), syscall.LOCK_UN); f.Close() }, true
}
