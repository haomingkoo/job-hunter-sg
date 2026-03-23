FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Railway sets PORT dynamically; default to 80 for local Docker
ENV PORT=80
ENV BACKEND_URL=http://localhost:8000

EXPOSE ${PORT}

# nginx:alpine supports /etc/nginx/templates/*.template — envsubst runs
# automatically via docker-entrypoint.d. But we only want to substitute
# our vars, not nginx's own $uri/$host etc.
CMD ["/bin/sh", "-c", "envsubst '$PORT $BACKEND_URL' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
