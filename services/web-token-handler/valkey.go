package main

// Oturum deposu için küçük bir Valkey (RESP2) istemcisi: AUTH, GET, SET EX, DEL. Bağımlılık eklememek için.
// Tek bağlantı, kilitle sıralanır; hata olursa bağlantı kapatılıp sonraki istekte yeniden kurulur.

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"sync"
	"time"
)

type valkey struct {
	addr, user, pass string
	mu               sync.Mutex
	conn             net.Conn
	rd               *bufio.Reader
}

func (v *valkey) setJSON(key string, val any, ttl time.Duration) error {
	b, err := json.Marshal(val)
	if err != nil {
		return err
	}
	_, _, err = v.do("SET", key, string(b), "EX", strconv.Itoa(int(ttl.Seconds())))
	return err
}

// getJSON: anahtar yoksa (false, nil)
func (v *valkey) getJSON(key string, out any) (bool, error) {
	s, ok, err := v.do("GET", key)
	if err != nil || !ok {
		return false, err
	}
	return true, json.Unmarshal([]byte(s), out)
}

func (v *valkey) del(key string) {
	v.do("DEL", key)
}

// do: komutu gönderir; dönüş: (değer, nil değil mi, hata)
func (v *valkey) do(args ...string) (string, bool, error) {
	v.mu.Lock()
	defer v.mu.Unlock()
	for attempt := 0; attempt < 2; attempt++ {
		if v.conn == nil {
			if err := v.connect(); err != nil {
				return "", false, err
			}
		}
		s, ok, err := v.roundTrip(args)
		var re respError
		if err == nil || errors.As(err, &re) { // sunucu hatası (ör. NOPERM) bağlantı hatası değil
			return s, ok, err
		}
		v.conn.Close()
		v.conn = nil
	}
	return "", false, errors.New("valkey: bağlantı kurulamadı")
}

func (v *valkey) connect() error {
	c, err := net.DialTimeout("tcp", v.addr, 3*time.Second)
	if err != nil {
		return err
	}
	v.conn, v.rd = c, bufio.NewReader(c)
	if v.user != "" {
		if _, _, err := v.roundTrip([]string{"AUTH", v.user, v.pass}); err != nil {
			c.Close()
			v.conn = nil
			return fmt.Errorf("valkey AUTH: %w", err)
		}
	}
	return nil
}

func (v *valkey) roundTrip(args []string) (string, bool, error) {
	v.conn.SetDeadline(time.Now().Add(3 * time.Second))
	buf := []byte("*" + strconv.Itoa(len(args)) + "\r\n")
	for _, a := range args {
		buf = append(buf, "$"+strconv.Itoa(len(a))+"\r\n"+a+"\r\n"...)
	}
	if _, err := v.conn.Write(buf); err != nil {
		return "", false, err
	}
	line, err := v.rd.ReadString('\n')
	if err != nil {
		return "", false, err
	}
	if len(line) < 3 {
		return "", false, errors.New("valkey: geçersiz yanıt")
	}
	body := line[1 : len(line)-2]
	switch line[0] {
	case '+', ':':
		return body, true, nil
	case '-':
		return "", false, respError(body)
	case '$':
		n, err := strconv.Atoi(body)
		if err != nil {
			return "", false, err
		}
		if n < 0 {
			return "", false, nil
		}
		data := make([]byte, n+2)
		if _, err := io.ReadFull(v.rd, data); err != nil {
			return "", false, err
		}
		return string(data[:n]), true, nil
	}
	return "", false, fmt.Errorf("valkey: beklenmeyen yanıt tipi %q", line[0])
}

type respError string

func (e respError) Error() string { return "valkey: " + string(e) }
