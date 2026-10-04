# DAX measures

```
Total Revenue = SUM(Orders[order_value])
```

```
Total Orders = COUNTROWS(Orders)
```

```
Avg Order Value = DIVIDE([Total Revenue], [Total Orders])
```

```
Avg Review Score = AVERAGE(Orders[review_score])
```

```
Avg Delivery Days = AVERAGE(Orders[delivery_days])
```

```
Late Orders = CALCULATE([Total Orders], Orders[delivery_status] = "Late")
```

```
Late Delivery % = DIVIDE([Late Orders], [Total Orders])
```

```
Repeat Customer Orders % = DIVIDE(CALCULATE([Total Orders], Orders[customer_type] = "Repeat"), [Total Orders])
```

```
Revenue Previous Month = CALCULATE([Total Revenue], DATEADD('Date'[Date], -1, MONTH))
```

```
MoM Growth % = DIVIDE([Total Revenue] - [Revenue Previous Month], [Revenue Previous Month])
```

```
Revenue YTD = TOTALYTD([Total Revenue], 'Date'[Date])
```

```
Revenue Share % = DIVIDE([Total Revenue], CALCULATE([Total Revenue], ALLSELECTED(Orders)))
```

```
Category Rank = RANKX(ALL(Orders[category]), [Total Revenue], , DESC, Dense)
```

```
Bad Review % = DIVIDE(CALCULATE([Total Orders], Orders[review_score] <= 2), CALCULATE([Total Orders], NOT ISBLANK(Orders[review_score])))
```
