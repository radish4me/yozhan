# The dashboard is a build-time artifact: compile it, then copy only the
# static output into the gateway image, so React and Vite never ship to
# production.
FROM node:22-slim AS dashboard
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json* /app/dashboard/
RUN npm install
COPY dashboard/ /app/dashboard/
RUN npm run build

FROM node:22-slim
WORKDIR /app/gateway

COPY gateway/package.json gateway/tsconfig.json /app/gateway/
RUN npm install

COPY gateway/src /app/gateway/src
RUN npm run build

COPY --from=dashboard /app/dashboard/dist /app/dashboard/dist
ENV DASHBOARD_DIR=/app/dashboard/dist

EXPOSE 3000
CMD ["node", "dist/index.js"]
