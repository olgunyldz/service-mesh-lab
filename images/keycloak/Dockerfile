# Keycloak'ın optimize image'ı: yapılandırma build aşamasında derlenir ("kc.sh build").
# Çalışma anında derleme olmaz: açılış hızlı ve CPU'yu zorlamaz, dosya sistemi salt okunur olabilir.
# Build zamanı seçenekleri burada; çalışma zamanı seçenekleri (DB adresi, hostname) manifest'te.
ARG KEYCLOAK_BASE_IMAGE
FROM ${KEYCLOAK_BASE_IMAGE} AS build
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_CACHE=local
RUN /opt/keycloak/bin/kc.sh build

FROM ${KEYCLOAK_BASE_IMAGE}
COPY --from=build /opt/keycloak/ /opt/keycloak/
USER 1000
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
