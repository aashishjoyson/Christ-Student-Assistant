# Web image: builds the React app, serves it with nginx and proxies /api to the API container.
# Build from the frontend folder:  docker build -t cu-helpdesk-web frontend
# NOT BUILT where it was written (the Docker engine was not running): the first `docker compose build` is the real test.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
