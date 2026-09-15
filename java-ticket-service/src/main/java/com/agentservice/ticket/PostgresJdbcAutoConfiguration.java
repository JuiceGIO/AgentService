package com.agentservice.ticket;

import org.springframework.boot.flyway.autoconfigure.FlywayAutoConfiguration;
import org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration;
import org.springframework.boot.jdbc.autoconfigure.JdbcTemplateAutoConfiguration;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Profile;

/**
 * 仅 postgres profile 生效：把默认排除的 DataSource/JdbcTemplate/Flyway 自动配置重新引入，
 * 保证内存模式（无 profile）不要求数据库、PG 模式自动建表两不误。
 */
@Configuration
@Profile("postgres")
@Import({
        DataSourceAutoConfiguration.class,
        JdbcTemplateAutoConfiguration.class,
        FlywayAutoConfiguration.class
})
public class PostgresJdbcAutoConfiguration {
}
