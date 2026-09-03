FROM node:22-bookworm-slim AS node-runtime

FROM docker.io/library/eclipse-temurin:21-jre-jammy

ARG FIREBASE_TOOLS_VERSION=15.28.1
ENV HOME=/firebase \
    FIREBASE_CLI_DISABLE_UPDATE_CHECK=true

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && mkdir -p /firebase \
    && npm install --global "firebase-tools@${FIREBASE_TOOLS_VERSION}" \
    && rm -rf /firebase/.npm

WORKDIR /firebase
COPY firebase.json firestore.rules firestore.indexes.json /firebase/
RUN firebase setup:emulators:firestore

WORKDIR /runtime
EXPOSE 8080
ENTRYPOINT ["firebase", "--config", "/firebase/firebase.json", "emulators:start", "--only", "firestore", "--project", "demo-job-application-agents"]
