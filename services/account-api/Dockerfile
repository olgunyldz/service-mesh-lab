# Çok aşamalı build: derleme golang image'ında, çalışma distroless/static (kabuk yok, paket yöneticisi yok, non-root).
ARG GO_BUILD_IMAGE
ARG GO_RUNTIME_IMAGE

FROM ${GO_BUILD_IMAGE} AS build
ARG VERSION=dev
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
# CGO kapalı: statik binary, libc gerekmez. -trimpath: build yolları binary'ye girmez
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=${VERSION}" -o /out/account-api .

FROM ${GO_RUNTIME_IMAGE}
COPY --from=build /out/account-api /account-api
# distroless "nonroot" kullanıcısı (UID 65532)
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/account-api"]
