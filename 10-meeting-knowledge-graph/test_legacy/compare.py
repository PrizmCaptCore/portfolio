import json

small = {r["i"]: r for r in json.load(open("replay_out.json", encoding="utf-8"))}
claude = {r["i"]: r for r in json.load(open("replay_claude.json", encoding="utf-8"))}

agree = total = 0
for i in sorted(small):
    if i not in claude:
        continue
    s, c = small[i].get("type", "?"), claude[i].get("type", "?")
    total += 1
    agree += s == c
    mark = "   " if s == c else " <-"
    print(f"{i:3} small={s:9} claude={c:9}{mark} {small[i]['msg'][:55]}")

print(f"\nmatch: {agree}/{total} ({agree / total:.0%})")

# only the disagreements
print("\n--- mismatches ---")
for i in sorted(small):
    if i in claude and small[i].get("type") != claude[i].get("type"):
        print(
            f"{i:3} {small[i].get('type'):9} vs {claude[i].get('type'):9}  {small[i]['msg'][:60]}"
        )
