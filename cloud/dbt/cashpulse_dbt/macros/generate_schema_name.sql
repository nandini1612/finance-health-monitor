{#
  dbt's default behavior prefixes custom schemas with the connection's
  target schema (e.g. "public_analytics"), which is meant for multi-team
  warehouses sharing one dbt project. For a single-project setup like this
  one, the standard override below is worth knowing: use the custom schema
  name exactly as configured in dbt_project.yml (+schema: staging / analytics),
  so the raw/staging/analytics/ml split stays clean and predictable for
  whoever queries the database directly (the dashboard, Power BI, Tableau).
  This is documented dbt-labs guidance, not a hack:
  https://docs.getdbt.com/docs/build/custom-schemas
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
