FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci && cp package-lock.json node_modules/.installed-lock.json

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
