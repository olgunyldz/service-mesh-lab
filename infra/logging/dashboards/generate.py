"""Loki panoları (10a): bu üreteç infra/logging/dashboards/*.json dosyalarını yazar; 07b-setup-logging.sh Grafana'ya yükler.
Çalıştırma: python infra/logging/dashboards/generate.py
  overview.json   -> Main Org (yönetici), veri kaynağı logs-all: tüm kategoriler, korelasyon
  <kategori>.json -> o kategorinin organizasyonu, veri kaynağı logs-<kategori>
Not: başarılı access log'lar 1/10 örneklenir (10 · logging); hata / ret / Envoy bayraklı istekler tam."""
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))
SAMPLED = "Başarılı (2xx/3xx) access log'lar request_id'ye göre 1/10 örneklenir; hata, ret ve bayraklı istekler tam."


class Board:
    def __init__(self, uid, title, ds, description, variables=()):
        self.uid, self.title, self.ds, self.description = uid, title, {"type": "loki", "uid": ds}, description
        self.panels, self.y, self.x, self.row_h, self.vars = [], 0, 0, 0, list(variables)

    def _add(self, panel, w, h):
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.row_h
            self.row_h = 0
        panel.update({"id": len(self.panels) + 1, "datasource": self.ds, "gridPos": {"x": self.x, "y": self.y, "w": w, "h": h}})
        self.panels.append(panel)
        self.x += w
        self.row_h = max(self.row_h, h)

    def row(self, title):
        self.x, self.y = 0, self.y + self.row_h
        self.row_h = 0
        self.panels.append({"id": len(self.panels) + 1, "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.y += 1

    def stat(self, title, expr, w=6, h=4, desc="", unit="short", color="blue"):
        self._add({"type": "stat", "title": title, "description": desc,
                   "targets": [{"refId": "A", "expr": expr, "queryType": "instant", "datasource": self.ds}],
                   "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "fixed", "fixedColor": color},
                                                "thresholds": {"mode": "absolute", "steps": [{"color": color, "value": None}]}},
                                   "overrides": []},
                   "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                               "colorMode": "value", "graphMode": "none", "textMode": "auto"}}, w, h)

    def series(self, title, expr, legend, w=12, h=8, desc="", unit="short", stack=True, draw="bars"):
        self._add({"type": "timeseries", "title": title, "description": desc,
                   "targets": [{"refId": "A", "expr": expr, "queryType": "range", "legendFormat": legend, "datasource": self.ds}],
                   "fieldConfig": {"defaults": {"unit": unit, "custom": {
                       "drawStyle": draw, "fillOpacity": 60 if draw == "bars" else 15, "lineWidth": 1,
                       "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}, "overrides": []},
                   "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["sum"]},
                               "tooltip": {"mode": "multi", "sort": "desc"}}}, w, h)

    def bars(self, title, expr, legend, w=12, h=8, desc=""):
        self._add({"type": "bargauge", "title": title, "description": desc,
                   "targets": [{"refId": "A", "expr": expr, "queryType": "instant", "legendFormat": legend, "datasource": self.ds}],
                   "fieldConfig": {"defaults": {"unit": "short", "color": {"mode": "continuous-BlYlRd"}}, "overrides": []},
                   "options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                               "reduceOptions": {"calcs": ["lastNotNull"], "values": False}}}, w, h)

    def logs(self, title, expr, w=24, h=12, desc=""):
        self._add({"type": "logs", "title": title, "description": desc,
                   "targets": [{"refId": "A", "expr": expr, "queryType": "range", "datasource": self.ds}],
                   "options": {"showTime": True, "wrapLogMessage": True, "prettifyLogMessage": False, "enableLogDetails": True,
                               "sortOrder": "Descending", "dedupStrategy": "none"}}, w, h)

    def write(self, name):
        doc = {"uid": self.uid, "title": self.title, "description": self.description, "tags": ["loki", "10-logging"],
               "timezone": "browser", "schemaVersion": 39, "refresh": "30s", "editable": True,
               "time": {"from": "now-1h", "to": "now"}, "templating": {"list": self.vars}, "panels": self.panels}
        with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")


def textbox(name, label, desc):
    return {"type": "textbox", "name": name, "label": label, "description": desc, "query": "", "current": {"text": "", "value": ""},
            "hide": 0}


ACCESS = '{category="network", container="istio-proxy"} | json'

# --- Genel bakış (yönetici, tüm kategoriler) ---
b = Board("logs-overview", "Loglar - Genel bakış", "logs-all",
          "Tüm zone'ların logları (Loki, beş kategori). request_id ile bir isteğin izini sürmek için yukarıdaki kutuya kimliği yazın. " + SAMPLED,
          [textbox("request_id", "request_id", "Bir isteğin kimliği (ör. api-a'nın gördüğü X-Request-Id)")])
b.row("Hacim")
for c, color in [("apps", "blue"), ("network", "purple"), ("security", "red"), ("db", "green"), ("infra", "orange")]:
    b.stat(c, f'sum(count_over_time({{category="{c}"}} [$__range]))', w=24 // 5 if c != "infra" else 24 - 4 * (24 // 5),
           desc=f"Seçili aralıkta {c} kategorisindeki satır sayısı", color=color)
b.series("Kategoriye göre log hacmi", 'sum by (category) (count_over_time({category=~".+"} [$__auto]))', "{{category}}", w=12)
b.series("Zone'a göre log hacmi", 'sum by (zone) (count_over_time({category=~".+"} [$__auto]))', "{{zone}}", w=12)
b.row("Güvenlik ve hatalar")
b.stat("WAF engellemesi", 'sum(count_over_time({category="security", cluster="edge"} |= "ModSecurity: Access denied" [$__range]))',
       desc="edge-waf'ın engellediği istekler (OWASP CRS)", color="red")
b.stat("auth-service reddi", 'sum(count_over_time({category="security", namespace="auth"} |= "RED channel=" [$__range]))',
       desc="Kanal kimlik kontrolünde reddedilen istekler (token yok, yanlış realm, cihaz, DPoP …)", color="orange")
b.stat("Dört göz ihlali", 'sum(count_over_time({category="security"} |= "DÖRT GÖZ İHLALİ" [$__range]))',
       desc="Kendi talebini onaylamaya çalışan personel", color="red")
b.stat("Secret değişikliği (audit)", 'sum(count_over_time({namespace="kube-audit"} | json | objectRef_resource="secrets" | verb=~"create|update|patch|delete" [$__range]))',
       desc="Kubernetes audit: secret oluşturma / güncelleme / silme", color="purple")
b.series("5xx yanıtlar (cluster'a göre)", f'sum by (cluster) (count_over_time({ACCESS} | response_code >= 500 [$__auto]))', "{{cluster}}",
         desc="Gateway ve waypoint access log'larında 5xx")
b.series("4xx yanıtlar (cluster'a göre)", f'sum by (cluster) (count_over_time({ACCESS} | response_code >= 400 | response_code < 500 [$__auto]))',
         "{{cluster}}", desc="401 / 403 / 404 / 429: kimlik, yetki, kota")
b.row("Korelasyon")
b.logs("request_id ile iz (tüm kategoriler, tüm zone'lar)", '{category=~".+"} |= "$request_id"', h=12,
       desc="Yukarıdaki request_id kutusu boşsa tüm loglar gelir. Aynı kimlik DMZ ve internal access log'larında ve auth-service logunda görünür")
b.logs("Son hatalar (5xx ve Envoy bayrakları)", f'{ACCESS} | response_code >= 500 or response_flags != "-"', h=10)
b.write("overview.json")

# --- Network ---
b = Board("logs-network", "Network - Access log'lar", "logs-network",
          "Gateway / waypoint access log'ları (JSON), ztunnel ve edge (HAProxy, WAF, branch-fw). " + SAMPLED)
b.series("Yanıt kodu", f'sum by (response_code) (count_over_time({ACCESS} [$__auto]))', "{{response_code}}", w=12)
b.series("Kanal", f'sum by (channel) (count_over_time({ACCESS} | channel != "" [$__auto]))', "{{channel}}", w=12)
b.series("Süre p95 (ms, cluster'a göre)",
         f'quantile_over_time(0.95, {ACCESS} | duration_ms != "" | unwrap duration_ms [$__auto]) by (cluster)', "{{cluster}}",
         w=12, unit="ms", stack=False, draw="line")
b.bars("Envoy yanıt bayrakları", f'sum by (response_flags) (count_over_time({ACCESS} | response_flags != "-" [$__range]))',
       "{{response_flags}}", w=12, desc="UH: sağlıklı upstream yok, UF: bağlantı hatası, URX: yeniden deneme sınırı, RL: kota, UAEX: ext_authz reddi …")
b.bars("En çok hata dönen hedefler", f'topk(10, sum by (authority, path) (count_over_time({ACCESS} | response_code >= 400 [$__range])))',
       "{{authority}}{{path}}", w=12)
b.bars("Edge container'ları", 'sum by (container) (count_over_time({cluster="edge"} [$__range]))', "{{container}}", w=12)
b.logs("Hatalı istekler", f'{ACCESS} | response_code >= 400', h=12)
b.write("network.json")

# --- Security ---
b = Board("logs-security", "Security - Güvenlik olayları", "logs-security",
          "WAF engellemeleri, Kubernetes audit, auth-service redleri, Keycloak giriş olayları, dört göz ihlali ve personel erişimi (uygulama loglarından kopya).")
b.stat("WAF engellemesi", 'sum(count_over_time({cluster="edge"} |= "ModSecurity: Access denied" [$__range]))', color="red")
b.stat("auth-service reddi", 'sum(count_over_time({namespace="auth"} |= "RED channel=" [$__range]))', color="orange")
b.stat("Keycloak giriş hatası", 'sum(count_over_time({namespace="iam"} |= "LOGIN_ERROR" [$__range]))', color="red")
b.stat("Personel erişimi", 'sum(count_over_time({category="security"} |= "PERSONEL ERİŞİMİ" [$__range]))', color="blue")
b.series("auth-service redleri (sebep)",
         'sum by (sebep) (count_over_time({namespace="auth"} |= "RED channel=" | regexp `sebep="(?P<sebep>[^"]*)"` [$__auto]))',
         "{{sebep}}", w=12)
b.series("WAF engellemeleri", 'sum by (zone) (count_over_time({cluster="edge"} |= "ModSecurity: Access denied" [$__auto]))', "{{zone}}", w=12)
b.bars("Audit: işlem ve kaynak", 'topk(15, sum by (verb, objectRef_resource) (count_over_time({namespace="kube-audit"} | json [$__range])))',
       "{{verb}} {{objectRef_resource}}", w=12)
b.bars("Audit: kim (kullanıcı)", 'topk(10, sum by (user_username) (count_over_time({namespace="kube-audit"} | json [$__range])))',
       "{{user_username}}", w=12)
b.logs("Secret erişimi (audit)", '{namespace="kube-audit"} | json | objectRef_resource="secrets"', h=10)
b.logs("Güvenlik olayları (WAF, ret, giriş hatası, dört göz)",
       '{category="security", namespace!="kube-audit"} |~ "ModSecurity: Access denied|RED channel=|LOGIN_ERROR|DÖRT GÖZ|MESAİ DIŞI"', h=12)
b.write("security.json")

# --- Apps ---
b = Board("logs-apps", "Apps - Uygulama logları", "logs-apps",
          "BFF'ler, account-api, auth-service, web token handler, device-registry, api-a.")
b.series("Servise göre log hacmi", 'sum by (namespace) (count_over_time({category="apps"} [$__auto]))', "{{namespace}}", w=12)
b.series("Hata satırları", 'sum by (namespace) (count_over_time({category="apps"} |~ "(?i)error|panic|fail" [$__auto]))', "{{namespace}}", w=12)
b.stat("Transfer kabul", 'sum(count_over_time({namespace="account-api"} |= "TRANSFER kabul" [$__range]))', color="green")
b.stat("Onay bekleyen transfer", 'sum(count_over_time({namespace="account-api"} |= "TRANSFER onay bekliyor" [$__range]))', color="orange")
b.stat("Onaylanan transfer", 'sum(count_over_time({namespace="account-api"} |= "TRANSFER onaylandı" [$__range]))', color="blue")
b.stat("auth-service izin / ret", 'sum(count_over_time({namespace="auth"} |= "İZİN channel=" [$__range]))', color="green")
b.logs("Transfer ve onay kayıtları", '{namespace="account-api"} |= "TRANSFER"', h=10)
b.logs("Hatalar", '{category="apps"} |~ "(?i)error|panic|fail"', h=10)
b.write("apps.json")

# --- DB ---
b = Board("logs-db", "DB - PostgreSQL ve Valkey", "logs-db", "Veri katmanı (mgmt / data).")
b.stat("Başarısız giriş", 'sum(count_over_time({category="db"} |= "password authentication failed" [$__range]))', color="red")
b.stat("Yetki reddi", 'sum(count_over_time({category="db"} |= "permission denied" [$__range]))', color="orange")
b.stat("Hata / FATAL", 'sum(count_over_time({category="db"} |~ "ERROR|FATAL" [$__range]))', color="red")
b.stat("Valkey ACL reddi", 'sum(count_over_time({category="db", container="valkey"} |~ "(?i)noperm|acl" [$__range]))', color="purple")
b.series("Container'a göre log hacmi", 'sum by (container) (count_over_time({category="db"} [$__auto]))', "{{container}}", w=24)
b.logs("Hatalar ve redler", '{category="db"} |~ "ERROR|FATAL|password authentication failed|permission denied"', h=12)
b.write("db.json")

# --- Infra ---
b = Board("logs-infra", "Infra - Platform uyarı ve hataları", "logs-infra",
          "Platform bileşenlerinin yalnızca uyarı ve hata satırları (10 · logging: infra süzmesi).")
b.series("Namespace'e göre uyarı / hata", 'sum by (namespace) (count_over_time({category="infra"} [$__auto]))', "{{namespace}}", w=12)
b.bars("En gürültülü container'lar", 'topk(10, sum by (namespace, container) (count_over_time({category="infra"} [$__range])))',
       "{{namespace}}/{{container}}", w=12)
b.series("Cluster'a göre", 'sum by (cluster) (count_over_time({category="infra"} [$__auto]))', "{{cluster}}", w=24)
b.logs("Uyarı ve hatalar", '{category="infra"}', h=14)
b.write("infra.json")
print("ok")
