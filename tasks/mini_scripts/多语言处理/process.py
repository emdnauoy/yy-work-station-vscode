import pandas as pd

df = pd.read_excel("D:/Projects/YaoYao/yy-work-station/tasks/mini_scripts/多语言处理/ALL.xlsx")
df_t = pd.read_excel("D:/Projects/YaoYao/yy-work-station/tasks/mini_scripts/多语言处理/msg多语言.xls") 


all_list = df.original_text.unique().tolist()

df_t1 = df_t[~df_t["Original"].isin(all_list)]

df_t1.to_excel("D:/Projects/YaoYao/yy-work-station/tasks/mini_scripts/多语言处理/分销订单.xlsx", index=False)