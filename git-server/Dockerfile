FROM alpine:latest
RUN apk add --no-cache git git-daemon
RUN mkdir -p /git/repo.git && \
    cd /git/repo.git && \
    git init --bare --shared=all && \
    git config receive.denyCurrentBranch ignore
EXPOSE 9418
CMD ["git", "daemon", "--reuseaddr", "--base-path=/git", "--export-all", "--verbose", "--enable=receive-pack"]
