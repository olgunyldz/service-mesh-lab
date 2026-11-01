#!/bin/sh
# Web kanalına tarayıcı gibi giriş (09a; 08-verify.sh kullanır). Edge ağındaki bir container'da çalışır:
#   /auth/login -> Keycloak giriş formu (ayse) -> /auth/callback -> __Host-sid cookie'si -> /auth/session (CSRF)
# STEPUP=1 (09b): ardından aynı tarayıcıyla /auth/login?acr=2 -> IdP'de açık oturum olduğu için yalnızca OTP sorulur.
# Ortam: WEB, SSO (host adları), PW (ayse'nin parolası), OTP (step-up için 6 haneli kod); /ca.pem edge CA'sı.
# Çıktı (anahtar=değer): SID, CSRF, SET_COOKIE (oturum cookie'sinin bayrakları), COOKIES (web host'undaki cookie adları),
# TOKEN_LEAK (tarayıcıya giden yanıtlarda görülen JWT sayısı; 0 olmalı), STEPS (girişte sorulan adımlar),
# STEPUP_STEPS (step-up'ta sorulan adımlar)
ip=$(getent hosts edge-lb | cut -d" " -f1)
J=/tmp/web.jar; H=/tmp/h; B=/tmp/b; S=/tmp/steps
c() { curl -s --max-time 15 --cacert /ca.pem --resolve "$WEB:8443:$ip" --resolve "$SSO:8443:$ip" -c $J -b $J "$@"; }

# login <yol>: /auth/login'den başlar, Keycloak formlarını (parola, OTP) doldurur, callback'i tamamlar
login() {
  : > $S
  loc=$(c -o $B -D $H -w "%{redirect_url}" "https://$WEB:8443$1")
  leak=$((leak + $(cat $H $B | grep -c "eyJ")))
  c "$loc" > $B
  cb=""
  for i in 1 2 3; do
    action=$(grep -o 'action="[^"]*login-actions/authenticate[^"]*"' $B | head -1 | cut -d'"' -f2 | sed 's/&amp;/\&/g')
    [ -z "$action" ] && break
    if grep -q 'name="otp"' $B; then
      grep -q otp $S && break   # aynı kod bir daha gönderilmez (yanlış deneme brute force sayacına yazılır)
      echo -n "otp " >> $S
      cb=$(c -o $B -w "%{redirect_url}" --data-urlencode "otp=$OTP" "$action")
    else
      echo -n "parola " >> $S
      cb=$(c -o $B -w "%{redirect_url}" --data-urlencode username=ayse --data-urlencode "password=$PW" "$action")
    fi
    [ -n "$cb" ] && break
  done
  c -o $B -D $H "$cb"
  leak=$((leak + $(cat $H $B | grep -c "eyJ")))
}

leak=0
login /auth/login
echo "STEPS=$(cat $S)"
echo "SET_COOKIE=$(grep -i '^set-cookie: __Host-sid=' $H | cut -d';' -f2- | tr -d '\r ')"
if [ "${STEPUP:-}" = 1 ]; then
  login "/auth/login?acr=2"
  echo "STEPUP_STEPS=$(cat $S)"
fi
c "https://$WEB:8443/auth/session" > $B
leak=$((leak + $(grep -c "eyJ" $B)))
echo "CSRF=$(sed -n 's/.*"csrf":"\([^"]*\)".*/\1/p' $B)"
echo "SID=$(awk '$6=="__Host-sid"{print $7}' $J)"
# curl HttpOnly cookie'leri "#HttpOnly_<host>" önekiyle yazar
echo "COOKIES=$(awk -v h="$WEB" 'NF>=7 && ($1==h || $1=="#HttpOnly_" h) {print $6}' $J | sort -u | tr '\n' ' ')"
echo "TOKEN_LEAK=$leak"
