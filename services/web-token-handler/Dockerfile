# Çok aşamalı build: derleme golang image'ında, çalışma distroless/static (kabuk yok, paket yöneticisi yok, non-root).
ARG GO_BUILD_IMAGE
ARG GO_RUNTIME_IMAGE

FROM ${GO_BUILD_IMAGE} AS build
ARG VERSION=dev
WORKDIR /src
COPY go.mod ./
COPY *.go ./
# CGO kapalı: statik binary, libc gerekmez. -trimpath: build yolları binary'ye girmez
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/web-token-handler .

FROM ${GO_RUNTIME_IMAGE}
COPY --from=build /out/web-token-handler /web-token-handler
# distroless "nonroot" kullanıcısı (UID 65532)
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/web-token-handler"]
