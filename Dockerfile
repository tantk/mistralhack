# Stage 1: Build frontend
FROM node:22-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json tsconfig.node.json vite.config.ts ./
COPY src/ src/
RUN npm run build

# Stage 2: Build backend
FROM rust:1.83-bookworm AS backend
RUN apt-get update && apt-get install -y clang libclang-dev cmake pkg-config && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY orchestrator/ orchestrator/
WORKDIR /app/orchestrator
RUN cargo build --release

# Stage 3: Runtime
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 app
USER 1000
WORKDIR /home/app
COPY --from=backend /app/orchestrator/target/release/orchestrator ./orchestrator
COPY --from=frontend /app/dist ./static
RUN mkdir -p data/voiceprints
ENV PORT=7860
EXPOSE 7860
CMD ["./orchestrator"]
