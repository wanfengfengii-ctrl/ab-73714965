# Web frontend: build static assets, then serve them with nginx.
FROM python:3.12-slim AS build
WORKDIR /build
COPY build.py ./
COPY src ./src
RUN python build.py --out dist

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
