FROM node:22-slim

WORKDIR /app/gateway

COPY gateway/package.json gateway/tsconfig.json /app/gateway/
RUN npm install

COPY gateway/src /app/gateway/src
RUN npm run build

EXPOSE 3000
CMD ["node", "dist/index.js"]
