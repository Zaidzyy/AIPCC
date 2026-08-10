FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
# `npm ci`, not `npm install`: it installs exactly what the lockfile pins and
# fails loudly if the lockfile and package.json disagree, so the image cannot
# quietly acquire a different dependency tree than the one that was tested.
RUN npm ci

COPY . .

EXPOSE 5173

# The dev server, deliberately. This is a portfolio stack meant to be read and
# poked at, and Vite's dev server is what the documented workflow uses. It is
# `vite --host` in package.json — without `--host` it binds to loopback inside
# the container and the published port reaches nothing.
CMD ["npm", "run", "dev"]
