package com.agentservice.ticket;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.flyway.autoconfigure.FlywayAutoConfiguration;
import org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration;
import org.springframework.boot.jdbc.autoconfigure.JdbcTemplateAutoConfiguration;
import org.springframework.scheduling.annotation.EnableScheduling;

// 默认（内存）模式不需要数据库：排除 JDBC/Flyway 自动配置；
// postgres profile 下由 PostgresJdbcAutoConfiguration 重新引入。
@SpringBootApplication(exclude = {
        DataSourceAutoConfiguration.class,
        JdbcTemplateAutoConfiguration.class,
        FlywayAutoConfiguration.class
})
@EnableScheduling
public class TicketApplication {
    public static void main(String[] args) {
        SpringApplication.run(TicketApplication.class, args);
    }
}
