import sys, time
sys.path.insert(0, ".")
from data.realtime_news import get_realtime_news

t0 = time.time()
df = get_realtime_news()
print(f"获取 {len(df)} 条新闻，耗时 {time.time()-t0:.1f}s")

has_content = df["content"].notna() & (df["content"].str.len() > 50)
print(f"有正文: {has_content.sum()} 条")
for _, row in df[has_content].head(5).iterrows():
    print(f"  [{row['source']}] {row['title'][:50]}")
    print(f"    正文 {len(row['content'])} 字: {row['content'][:80]}...")
