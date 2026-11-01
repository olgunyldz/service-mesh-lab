#!/bin/sh
# Web kanalına tarayıcı gibi giriş (09a; 08-verify.sh kullanır). Edge ağındaki bir container'da çalışır:
#   /auth/login -> Keycloak giriş formu (ayse) -> /auth/callback -> __Host-sid cookie'si -> /auth/session (CSRF)
# Ortam: WEB, SSO (host adları), PW (ayse'nin parolası); /ca.pem edge CA'sı.
# Çıktı (anahtar=değer): SID, CSRF, SET_COOKIE (oturum cookie'sinin bayrakları), COOKIES (web host'undaki cookie adları),
# TOKEN_LEAK (tarayıcıya giden yanıtlarda görülen JWT sayısı; 0 olmalı)
ip=$(getent hosts edge-lb | cut -d" " -f1)
J=/tmp/web.jar; H=/tmp/h; B=/tmp/b
c() { curl -s --max-time 15 --cacert /ca.pem --resolve "$WEB:8443:$ip" --resolve "$SSO:8443:$ip" -c $J -b $J "$@"; }

loc=$(c -o $B -D $H -w "%{redirect_url}" "https://$WEB:8443/auth/login")
leak=$(cat $H $B | grep -c "eyJ")
action=$(c "$loc" | grep -o 'action="[^"]*login-actions/authenticate[^"]*"' | head -1 | cut -d'"' -f2 | sed 's/&amp;/\&/g')
cb=$(c -o /dev/null -w "%{redirect_url}" --data-urlencode username=ayse --data-urlencode "password=$PW" "$action")
c -o $B -D $H "$cb"
leak=$((leak + $(cat $H $B | grep -c "eyJ")))
echo "SET_COOKIE=$(grep -i '^set-cookie: __Host-sid=' $H | cut -d';' -f2- | tr -d '\r ')"
c "https://$WEB:8443/auth/session" > $B
leak=$((leak + $(grep -c "eyJ" $B)))
echo "CSRF=$(sed -n 's/.*"csrf":"\([^"]*\)".*/\1/p' $B)"
echo "SID=$(awk '$6=="__Host-sid"{print $7}' $J)"
# curl HttpOnly cookie'leri "#HttpOnly_<host>" önekiyle yazar
echo "COOKIES=$(awk -v h="$WEB" 'NF>=7 && ($1==h || $1=="#HttpOnly_" h) {print $6}' $J | sort -u | tr '\n' ' ')"
echo "TOKEN_LEAK=$leak"
