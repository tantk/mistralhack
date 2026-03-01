# Stage 1: Install cargo-chef
FROM rust:1.85-bookworm AS chef
RUN cargo install cargo-chef
RUN apt-get update && apt-get install -y clang libclang-dev cmake pkg-config && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# Stage 2: Prepare dependency recipe (changes only when Cargo.toml/lock change)
FROM chef AS planner
COPY orchestrator/ orchestrator/
RUN cd orchestrator && cargo chef prepare --recipe-path recipe.json

# Stage 3: Cook dependencies (cached unless Cargo.toml/lock change)
FROM chef AS backend
COPY --from=planner /app/orchestrator/recipe.json orchestrator/recipe.json
RUN cd orchestrator && cargo chef cook --release --recipe-path recipe.json
COPY orchestrator/ orchestrator/
WORKDIR /app/orchestrator
RUN cargo build --release

# Stage 4: Build frontend (fast rebuild on UI-only changes)
FROM node:22-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json tsconfig.node.json vite.config.ts postcss.config.js tailwind.config.js ./
COPY src/ src/
RUN npm run build

# Stage 5: Runtime
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
