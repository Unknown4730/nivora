FROM node:20-alpine
WORKDIR /app
COPY . .
EXPOSE 8080
CMD ["npx", "--yes", "serve", ".", "-l", "8080"]
