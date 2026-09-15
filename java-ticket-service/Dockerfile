# Java 镜像使用本机 Maven 已打好的 jar（避免容器内访问 Maven Central 不稳定）。
# 若 target/ticket-service-0.1.0.jar 缺失，先在本机执行 mvn -q package 再构建镜像。
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY target/ticket-service-0.1.0.jar ./app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
