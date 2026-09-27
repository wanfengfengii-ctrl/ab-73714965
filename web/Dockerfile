# 构建阶段：TypeScript 类型检查 + Vite 打包
FROM node:20-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# 运行阶段：nginx 托管静态文件并反向代理 /api
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
