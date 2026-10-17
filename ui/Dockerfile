# The web console: built with Node, served by an unprivileged nginx that proxies /v1 to the
# API and adds the API key there, so the key never reaches the browser.
FROM node:24-alpine AS build
WORKDIR /ui
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npx vite build

FROM nginxinc/nginx-unprivileged:1.27-alpine
# The image renders /etc/nginx/templates/*.template with envsubst at start-up.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /ui/dist /usr/share/nginx/html
ENV MANDATE_API_UPSTREAM=api:8000
EXPOSE 8080
