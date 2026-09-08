# SKF 交叉销售规则（Cross-Sell Association Rules）

数据说明：Confidence = 历史数据置信度；Priority = 推荐优先级。主产品既可以是具体 SKU，也可以是产品类别或应用场景。

| Primary Product | Recommended Add-On | Confidence | Reason | Priority |
|-----------------|--------------------|------------|--------|----------|
| 22320 E | CR 100x120x12 Seal | 94% | Dusty environment protection（粉尘环境防护） | High |
| 22320 E | LGEP 2 Grease (18kg) | 91% | Heavy load lubrication（重载润滑） | High |
| 22320 E | TKTL 10 Heater | 78% | Proper installation（正确安装） | Medium |
| Any Spherical Roller | Matching Seal | 88% | Contamination prevention（防污染） | High |
| Any Spherical Roller | LGEP 2 or LGHP 2 | 85% | Extended bearing life（延长轴承寿命） | High |
| 6205-2RS | TMBA 10 Tool Set | 72% | Installation efficiency（安装效率） | Medium |
| 6308-2RS | LGMT 2 Grease | 80% | General purpose lubrication（通用润滑） | Medium |
| Any Bearing >100mm bore | TKTL 10 or TKTL 20 | 86% | Thermal installation required（需热装） | High |
| SY 50 TF | CR 80x100x10 | 79% | Shaft sealing（轴密封） | Medium |
| SNL 511 | 22212 E Bearing | 95% | Complete assembly（完整装配） | High |
| SNL 511 | CR Seal Set | 82% | Housing seals（轴承座密封） | Medium |
| Pump Application | 6205-2RS + LGHP 2 | 87% | High-speed, continuous duty（高速连续运行） | High |
| Motor Application | 6205-2RS/C3 + LGMT 2 | 90% | Standard motor setup（标准电机配置） | High |
| Fan Application (High Temp) | 22320 E/C3 + LGHP 2 | 93% | Temperature resistance（耐高温） | High |
| Conveyor Application | 22216 E + LGEP 2 + Seal | 91% | Heavy load, contaminated（重载污染环境） | High |
| Gearbox Application | 32210/32212 + LGEP 2 | 88% | High torque, shock load（高扭矩冲击载荷） | High |
| Agricultural Machinery | Sealed Bearing + Extra Seal Kit | 85% | Extreme contamination（极端污染） | High |
| Food Industry | Stainless Bearing + Food-Grade Grease | 92% | Hygiene compliance（卫生合规） | High |
| Any Bearing Purchase | CMSS 200-VL Sensor | 68% | Predictive maintenance upsell（预测性维护） | Low |
| Order >¥50K | TKTL 10 Heater (discounted) | 75% | Tool adoption program（工具推广计划） | Medium |

## 交叉销售逻辑（Cross-Sell Logic）

1. **Mandatory（必推）**：所有开放式轴承必须推荐密封件 + 润滑脂（目标附加率 90%+）
2. **Strong（强推）**：内径 >100mm 的轴承推荐安装工具（目标附加率 70%+）
3. **Opportunistic（机会型）**：战略客户推荐状态监测设备（目标附加率 30%+）
4. **Volume-based（组合优惠）**：3 件以上互补商品可享捆绑折扣

## 业务目标（AOV Impact）

- 无交叉销售平均订单额：¥8,500
- 有交叉销售平均订单额：¥10,200（+20%）
- 目标平均订单额：¥11,000（+29%）
