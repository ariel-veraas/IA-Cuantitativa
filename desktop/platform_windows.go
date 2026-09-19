package main

import (
	"os/exec"
	"syscall"
	"unsafe"
)

func hideWindow(c *exec.Cmd) { c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true} }
func openBrowser(url string) {
	c := exec.Command("rundll32.exe", "url.dll,FileProtocolHandler", url)
	hideWindow(c)
	c.Start()
}
func fatalMessage(message string) {
	u := syscall.NewLazyDLL("user32.dll")
	text, _ := syscall.UTF16PtrFromString(message)
	title, _ := syscall.UTF16PtrFromString("IA Cuantitativa")
	u.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(title)), 0x10)
}
func instanceLock(root string) (func(), bool) {
	k := syscall.NewLazyDLL("kernel32.dll")
	name, _ := syscall.UTF16PtrFromString("Local\\IA-Cuantitativa-Desktop")
	handle, _, err := k.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(name)))
	if handle == 0 || err == syscall.Errno(183) {
		if handle != 0 {
			k.NewProc("CloseHandle").Call(handle)
		}
		return func() {}, false
	}
	return func() { k.NewProc("CloseHandle").Call(handle) }, true
}
