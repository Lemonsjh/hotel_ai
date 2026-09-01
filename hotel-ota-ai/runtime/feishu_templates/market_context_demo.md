【S4 环境行情感知】

一、数据范围
- 酒店：{resolved_hotel_id}
- 业务日期：{business_date}
- 状态：{market_context_status}

二、来源
- weather_source：{weather_source}
- event_source：{event_source}
- holiday_source：{holiday_source}
- regional_heat_source：{regional_heat_source}

三、外部信号
- weather_signal：{weather_signal}
- weather_risk_level：{weather_risk_level}
- local_event_count：{local_event_count}
- event_heat_level：{event_heat_level}
- regional_heat_index：{regional_heat_index}

四、安全边界
- direct_price_trigger_allowed=false
- 外部天气、节假日、活动和商圈热度只能作为行情参考，不能单独触发调价。
