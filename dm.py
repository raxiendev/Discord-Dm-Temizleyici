"""Discord DM Temizleyici - DM kanalindaki mesajlari toplu siler."""

import http.client
import json
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import messagebox, scrolledtext, ttk

API_HOST = "discord.com"
API_BASE = "/api/v9"
API_URL = f"https://{API_HOST}{API_BASE}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20

_thread_state = threading.local()


def get_connection():
    conn = getattr(_thread_state, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(API_HOST, timeout=REQUEST_TIMEOUT)
        _thread_state.conn = conn
    return conn


def reset_connection():
    old = getattr(_thread_state, "conn", None)
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    conn = http.client.HTTPSConnection(API_HOST, timeout=REQUEST_TIMEOUT)
    _thread_state.conn = conn
    return conn


def api_request_fast(token, method, path, params=None):
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    target = f"{API_BASE}{path}{query}"
    headers = {
        "Authorization": token.strip(),
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    for attempt in range(2):
        try:
            conn = get_connection()
            conn.request(method, target, body=None, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            status = response.status
            resp_headers = {k.lower(): v for k, v in response.getheaders()}
            if not raw:
                return None, status, resp_headers
            text = raw.decode("utf-8", errors="ignore")
            if not text:
                return None, status, resp_headers
            try:
                return json.loads(text), status, resp_headers
            except ValueError:
                return text, status, resp_headers
        except Exception as exc:
            if attempt == 0:
                try:
                    reset_connection()
                    continue
                except Exception:
                    return {"error": str(exc)}, 0, {}
            return {"error": str(exc)}, 0, {}
    return {"error": "connection failed"}, 0, {}


def get_messages_fast(token, channel_id, before=None, limit=100):
    params = {"limit": limit}
    if before:
        params["before"] = before
    return api_request_fast(token, "GET", f"/channels/{channel_id}/messages", params=params)


def delete_message_fast(token, channel_id, message_id):
    return api_request_fast(token, "DELETE", f"/channels/{channel_id}/messages/{message_id}")


def get_retry_after(data, headers, default=1.5):
    try:
        if isinstance(data, dict) and "retry_after" in data:
            return float(data["retry_after"])
    except (TypeError, ValueError):
        pass
    try:
        value = headers.get("x-ratelimit-reset-after") or headers.get("retry-after")
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        pass
    return default


def api_request(token, method, path, data=None, params=None):
    url = f"{API_URL}{path}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"
    headers = {
        "Authorization": token.strip(),
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            status = resp.status
            resp_headers = dict(resp.headers)
            if not text:
                return None, status, resp_headers
            try:
                return json.loads(text), status, resp_headers
            except ValueError:
                return text, status, resp_headers
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            raw = ""
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {"raw": raw}
        try:
            exc_headers = dict(exc.headers)
        except Exception:
            exc_headers = {}
        return payload, exc.code, exc_headers
    except Exception as exc:
        return {"error": str(exc)}, 0, {}


def get_current_user(token):
    return api_request(token, "GET", "/users/@me")


def get_dm_channels(token):
    return api_request(token, "GET", "/users/@me/channels")


def get_messages(token, channel_id, before=None, limit=100):
    params = {"limit": limit}
    if before:
        params["before"] = before
    return api_request(token, "GET", f"/channels/{channel_id}/messages", params=params)

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Discord DM Temizleyici")
        self.root.geometry("700x660")
        self.root.minsize(600, 550)

        self.token_var = tk.StringVar()
        self.channel_var = tk.StringVar()
        self.only_mine_var = tk.BooleanVar(value=False)
        self.skip_others_var = tk.BooleanVar(value=True)
        self.delay_var = tk.DoubleVar(value=0.15)

        self.running = False
        self.user_id = None
        self.dm_map = {}
        self.status_var = tk.StringVar(value="Hazır")

        self._build_ui()
        self.log("Hazır. Token girin, DM'leri yükleyin, konuşma seçin, tarayın ve silin.\n")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Token").pack(anchor="w")
        token_row = ttk.Frame(main)
        token_row.pack(fill="x", pady=4)
        self.token_entry = ttk.Entry(token_row, textvariable=self.token_var, show="*", width=60)
        self.token_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(token_row, text="Göster / Gizle", command=self.toggle_token).pack(side="left", padx=5)

        conn_row = ttk.Frame(main)
        conn_row.pack(fill="x", pady=4)
        ttk.Button(conn_row, text="Bağlan ve DM'leri Yükle", command=self._start_list_dms).pack(side="left")
        self.info_label = ttk.Label(conn_row, text="Bağlı değil")
        self.info_label.pack(side="left", padx=8)

        ttk.Label(main, text="Konuşma").pack(anchor="w", pady=(8, 0))
        dm_row = ttk.Frame(main)
        dm_row.pack(fill="x", pady=4)
        self.dm_combo = ttk.Combobox(dm_row, state="readonly", width=50)
        self.dm_combo.pack(side="left", fill="x", expand=True)
        self.dm_combo.bind("<<ComboboxSelected>>", self.on_dm_select)
        ttk.Button(dm_row, text="Yenile", command=self._start_list_dms).pack(side="left", padx=5)

        ttk.Label(main, text="veya Kanal ID'yi elle girin:").pack(anchor="w")
        ttk.Entry(main, textvariable=self.channel_var, width=40).pack(anchor="w", pady=2)

        options = ttk.LabelFrame(main, text="Seçenekler", padding=8)
        options.pack(fill="x", pady=6)
        ttk.Checkbutton(
            options,
            text="Yalnızca benim mesajlarımı sil",
            variable=self.only_mine_var,
        ).pack(anchor="w")
        ttk.Checkbutton(
            options,
            text="Başkalarının mesajlarını denemeden atla (önerilir, daha hızlı)",
            variable=self.skip_others_var,
        ).pack(anchor="w")
        ttk.Label(options, text="Mesajlar arası bekleme (saniye):").pack(anchor="w", pady=(6, 0))
        ttk.Scale(options, from_=0.0, to=1.0, variable=self.delay_var, orient="horizontal").pack(fill="x")
        self.delay_label = ttk.Label(options, text="0.15 sn")
        self.delay_label.pack(anchor="w")
        self.delay_var.trace_add("write", self._update_delay_label)

        actions = ttk.Frame(main)
        actions.pack(fill="x", pady=6)
        ttk.Button(actions, text="Tara", command=self._start_scan).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Silmeyi Başlat", command=self.confirm_and_start).pack(side="left")
        ttk.Button(actions, text="Durdur", command=self.stop).pack(side="left", padx=6)

        self.status_label = ttk.Label(main, textvariable=self.status_var, font=("TkDefaultFont", 9, "bold"))
        self.status_label.pack(anchor="w")

        self.log_widget = scrolledtext.ScrolledText(main, height=12, state="normal")
        self.log_widget.pack(fill="both", expand=True, pady=6)

    def _update_delay_label(self, *args):
        try:
            self.delay_label.config(text=f"{self.delay_var.get():.2f} sn")
        except Exception:
            pass
    def toggle_token(self):
        current = self.token_entry.cget("show")
        self.token_entry.config(show="" if current == "*" else "*")

    def log(self, message):
        try:
            self.log_widget.insert("end", message)
            self.log_widget.see("end")
            self.root.update_idletasks()
        except Exception:
            pass

    def log_threadsafe(self, message):
        try:
            self.root.after(0, lambda: self.log(message))
        except Exception:
            pass

    def set_status(self, text):
        try:
            self.root.after(0, lambda: self.status_var.set(text))
        except Exception:
            pass

    def on_dm_select(self, event=None):
        name = self.dm_combo.get()
        if name in self.dm_map:
            self.channel_var.set(self.dm_map[name])

    def _start_list_dms(self):
        threading.Thread(target=self.list_dms, daemon=True).start()

    def _start_scan(self):
        threading.Thread(target=self.scan_channel, daemon=True).start()

    def get_token(self):
        return self.token_var.get().strip()

    def ensure_user(self, token):
        if self.user_id:
            return True
        data, code, _ = get_current_user(token)
        if code != 200 or not isinstance(data, dict) or "id" not in data:
            self.log_threadsafe(f"Token hatası: {data} (kod={code})\n")
            return False
        self.user_id = str(data.get("id"))
        try:
            username = data.get("username", "bilinmiyor")
            self.root.after(0, lambda: self.info_label.config(
                text=f"Bağlı: {username} ({self.user_id})"))
        except Exception:
            pass
        return True

    def list_dms(self):
        token = self.get_token()
        if len(token) < 20:
            messagebox.showwarning("Token Eksik", "Lütfen önce geçerli bir token girin.")
            return
        self.log_threadsafe("Bağlanıyor...\n")
        me, code, _ = get_current_user(token)
        if code != 200 or not isinstance(me, dict) or "id" not in me:
            self.log_threadsafe(f"Hata: geçersiz token (kod={code}).\n")
            return
        self.user_id = str(me.get("id"))
        username = me.get("username", "bilinmiyor")
        try:
            self.root.after(0, lambda: self.info_label.config(
                text=f"Bağlı: {username} ({self.user_id})"))
        except Exception:
            pass
        self.log_threadsafe(f"{username} olarak giriş yapıldı. DM'ler yükleniyor...\n")
        data, code, _ = get_dm_channels(token)
        if code != 200 or not isinstance(data, list):
            self.log_threadsafe(f"DM listesi yüklenemedi: {data}\n")
            return
        self.dm_map.clear()
        names = []
        for channel in data:
            cid = str(channel.get("id", ""))
            ctype = channel.get("type")
            recipients = channel.get("recipients", []) or []
            if ctype == 1 and recipients:
                user = recipients[0]
                label = f"{user.get('username')} - {user.get('id')} | {cid}"
                self.dm_map[label] = cid
                names.append(label)
            elif ctype == 3:
                label = f"Grup: {channel.get('name', 'isimsiz')} | {cid}"
                self.dm_map[label] = cid
                names.append(label)
        def _apply():
            self.dm_combo["values"] = names
            if names:
                self.dm_combo.set(names[0])
                self.on_dm_select()
        try:
            self.root.after(0, _apply)
        except Exception:
            pass
        self.log_threadsafe(f"{len(names)} konuşma bulundu.\n")

    def scan_channel(self):
        token = self.get_token()
        channel_id = self.channel_var.get().strip()
        if not token or not channel_id:
            messagebox.showwarning("Eksik Bilgi", "Token ve Kanal ID gereklidir.")
            return
        if not self.ensure_user(token):
            return
        self.log_threadsafe(f"Kanal taranıyor: {channel_id}...\n")
        before = None
        total = 0
        mine = 0
        while True:
            data, code, _ = get_messages(token, channel_id, before=before)
            if code == 429:
                wait = get_retry_after(data, {}, 2.0)
                self.log_threadsafe(f"Hız sınırı aşıldı. {wait:.1f} sn bekleniyor...\n")
                time.sleep(wait + 0.5)
                continue
            if code != 200 or not data:
                break
            for msg in data:
                total += 1
                author_id = str(msg.get("author", {}).get("id", ""))
                if author_id == str(self.user_id):
                    mine += 1
            before = data[-1]["id"]
            self.log_threadsafe(f"Taranan: {total}, sizinki: {mine}...\n")
            if len(data) < 100:
                break
            time.sleep(0.4)
        self.log_threadsafe(f"Tarama tamamlandı. Toplam: {total}, silinebilir (sizinki): {mine}\n")
    def confirm_and_start(self):
        channel_id = self.channel_var.get().strip()
        if not channel_id:
            messagebox.showwarning("Eksik Bilgi", "Bir konuşma seçin veya Kanal ID girin.")
            return
        if self.running:
            messagebox.showinfo("Zaten Çalışıyor", "Silme işlemi zaten çalışıyor.")
            return
        ok = messagebox.askyesno(
            "Onay",
            f"Kanaldaki ({channel_id}) silinebilir tüm mesajlar silinecek.\n"
            "Bu işlem geri alınamaz. Devam edilsin mi?",
        )
        if not ok:
            return
        ok = messagebox.askyesno("Son Onay", "Silme şimdi başlatılsın mı?")
        if not ok:
            return
        threading.Thread(target=self.run_delete, daemon=True).start()

    def stop(self):
        self.running = False
        self.log_threadsafe("Durdurma istendi...\n")

    @staticmethod
    def describe_message(message):
        content = str(message.get("content", "") or "")
        attachments = message.get("attachments", []) or []
        suffix = ""
        if attachments:
            names = ",".join(str(a.get("filename", "?"))[:20] for a in attachments)
            suffix += f" [dosya:{len(attachments)} {names}]"
        embeds = message.get("embeds") or []
        if embeds:
            suffix += f" [gömülü:{len(embeds)}]"
        if message.get("sticker_items"):
            suffix += " [çıkartma]"
        preview = content[:50] if content else "(resim/dosya)"
        return preview + suffix

    def run_delete(self):
        token = self.get_token()
        channel_id = self.channel_var.get().strip()
        if not token or not channel_id:
            messagebox.showwarning("Eksik Bilgi", "Token ve Kanal ID gereklidir.")
            return
        try:
            delay = float(self.delay_var.get())
        except Exception:
            delay = 0.15
        delay = max(0.0, delay)
        self.running = True
        started_at = time.time()
        self.log_threadsafe(f"Silme başladı (kanal={channel_id}, bekleme={delay:.2f} sn).\n")
        if not self.ensure_user(token):
            self.running = False
            return
        skip_others = bool(self.only_mine_var.get() or self.skip_others_var.get())
        deleted = 0
        skipped = 0
        forbidden = 0
        failed = 0
        scanned = 0
        last_update = 0.0
        cycle = 0
        while self.running:
            cycle += 1
            before = None
            cycle_deleted = 0
            cycle_attempts = 0
            cycle_retries = 0
            if cycle > 1:
                self.log_threadsafe(f"Tur {cycle}: kalan mesajlar yeniden taranıyor...\n")
            while self.running:
                data, code, headers = get_messages_fast(token, channel_id, before=before)
                if code == 429:
                    wait = get_retry_after(data, headers, 2.0)
                    self.log_threadsafe(f"Hız sınırı aşıldı (okuma). {wait:.1f} sn bekleniyor...\n")
                    time.sleep(wait + 0.3)
                    continue
                if code != 200:
                    self.log_threadsafe(f"Okuma hatası {code}: {data}\n")
                    break
                if not data:
                    break
                for msg in data:
                    if not self.running:
                        break
                    message_id = msg.get("id")
                    if not message_id:
                        continue
                    scanned += 1
                    author_id = str(msg.get("author", {}).get("id", ""))
                    if skip_others and author_id != str(self.user_id):
                        skipped += 1
                        continue
                    cycle_attempts += 1
                    description = self.describe_message(msg)
                    completed = False
                    forbidden_hit = False
                    permanent = False
                    for _ in range(6):
                        if not self.running:
                            break
                        result, status, resp_headers = delete_message_fast(token, channel_id, message_id)
                        if status in (200, 204, 404):
                            deleted += 1
                            cycle_deleted += 1
                            completed = True
                            break
                        if status == 429:
                            wait = get_retry_after(result, resp_headers, 1.2)
                            time.sleep(wait + 0.2)
                            continue
                        if status == 403:
                            forbidden += 1
                            forbidden_hit = True
                            break
                        if status == 0 or (isinstance(status, int) and status >= 500):
                            time.sleep(0.5)
                            continue
                        failed += 1
                        permanent = True
                        self.log_threadsafe(f"Silinemedi {message_id} (kod={status}) | {description}\n")
                        break
                    if not (completed or forbidden_hit or permanent):
                        cycle_retries += 1
                        failed += 1
                        self.log_threadsafe(f"Tekrar denenecek hata {message_id} -> sonraki turda denenecek\n")
                    now = time.time()
                    if now - last_update > 0.8:
                        last_update = now
                        rate = deleted / max(now - started_at, 0.1)
                        self.set_status(f"Tur:{cycle} Silinen:{deleted} Atlanan:{skipped + forbidden} Hata:{failed} {rate:.1f}/sn")
                        self.log_threadsafe(f"[{deleted}] silindi: {message_id} | {description}\n")
                    if delay > 0:
                        time.sleep(delay)
                if not self.running:
                    break
                before = data[-1]["id"]
                if len(data) < 100:
                    break
            if not self.running:
                break
            if cycle_attempts == 0:
                self.log_threadsafe(f"Tur {cycle}: silinebilir mesaj bulunamadı. Durduruluyor.\n")
                break
            self.log_threadsafe(f"Tur {cycle} bitti: silinen={cycle_deleted} denenen={cycle_attempts} tekrar={cycle_retries}\n")
            if cycle_deleted == 0 and cycle_retries == 0:
                self.log_threadsafe("Silinebilir mesaj kalmadı. Tamamlandı.\n")
                break
            time.sleep(1.0)
        self.running = False
        elapsed = max(time.time() - started_at, 0.1)
        rate = deleted / elapsed
        self.set_status(f"Silinen:{deleted} Atlanan:{skipped + forbidden} Hata:{failed} {rate:.1f}/sn")
        self.log_threadsafe(
            f"{elapsed:.0f} sn'de tamamlandı ({rate:.1f}/sn, {cycle} tur). "
            f"Silinen:{deleted} Atlanan:{skipped} Yetkisiz:{forbidden} "
            f"Başarısız:{failed} Taranan:{scanned}\n"
        )
        try:
            messagebox.showinfo(
                "Tamamlandı",
                f"Silinen: {deleted} ({rate:.1f}/sn)\n"
                f"Atlanan: {skipped + forbidden}\n"
                f"Başarısız: {failed}\n"
                f"Tur: {cycle}\n"
                f"Süre: {elapsed:.0f} sn",
            )
        except Exception:
            pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()



