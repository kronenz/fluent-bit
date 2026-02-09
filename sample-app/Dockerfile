FROM alpine:3.19
COPY log-generator.sh /scripts/log-generator.sh
RUN chmod +x /scripts/log-generator.sh
ENV LOG_PATH=/var/log/sample-app
ENV NAMESPACE=sample-app
CMD ["sh", "/scripts/log-generator.sh"]
