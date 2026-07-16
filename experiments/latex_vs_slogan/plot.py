import os, json, re, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE=os.path.dirname(os.path.abspath(__file__))
items=json.load(open(os.path.join(HERE,"data","results.json")))

def notation_density(s):
    math_spans=re.findall(r"\$[^$]*\$|\\\([^)]*\\\)|\\\[[^]]*\\\]", s)
    math_chars=sum(len(m) for m in math_spans)
    sym=len(re.findall(r"[=<>+\^_{}|\\]", s))
    return (math_chars+sym)/max(len(s),1)
for it in items:
    it["notdens"]=notation_density(it["raw"])
BLUE="#0072B2"; VERM="#D55E00"; GRAY="#5A5A5A"; INK="#222222"
plt.rcParams.update({"font.size":10,"axes.edgecolor":"#BBBBBB","axes.linewidth":0.8,
                     "font.family":"DejaVu Sans","text.color":INK,"axes.labelcolor":INK,
                     "xtick.color":INK,"ytick.color":INK})

gap=np.array([it["asym_gap"] for it in items])
nd=np.array([it["notdens"] for it in items])
cats=sorted(set(it["category"] for it in items))

fig,axes=plt.subplots(1,3,figsize=(14.5,4.4))

# -------- Panel A: distribution of the gap --------
ax=axes[0]
bins=np.linspace(-0.10,0.22,25)
ax.hist(gap[gap>0],bins=bins,color=BLUE,alpha=0.9,label="slogan closer")
ax.hist(gap[gap<=0],bins=bins,color=VERM,alpha=0.9,label="raw LaTeX closer")
ax.axvline(0,color=GRAY,lw=1.2,ls="--")
ax.set_xlabel("cosine gap  (slogan − raw LaTeX)  to the NL query")
ax.set_ylabel("theorems")
ax.set_title("A · Per-theorem winner  (n=100)",loc="left",fontweight="bold")
ax.text(0.105,ax.get_ylim()[1]*0.86,f"slogan closer\n{np.mean(gap>0):.0%} of theorems",
        color=BLUE,fontsize=10,ha="left",va="top",fontweight="bold")
ax.text(-0.096,ax.get_ylim()[1]*0.60,f"raw LaTeX\ncloser\n{np.mean(gap<=0):.0%}",
        color=VERM,fontsize=10,ha="left",va="top",fontweight="bold")
ax.spines[["top","right"]].set_visible(False)
ax.grid(axis="y",color="#EEEEEE")

# -------- Panel B: per-tag mean gap --------
ax=axes[1]
means=[(c,np.mean([it["asym_gap"] for it in items if it["category"]==c]),
          np.mean([it["asym_gap"]>0 for it in items if it["category"]==c])) for c in cats]
means.sort(key=lambda x:x[1])
labels=[m[0].replace("math.","") for m in means]; vals=[m[1] for m in means]; wr=[m[2] for m in means]
y=np.arange(len(labels))
ax.barh(y,vals,color=BLUE,height=0.62)
ax.set_yticks(y); ax.set_yticklabels(labels)
ax.axvline(0,color=GRAY,lw=1)
for yi,(v,w) in enumerate(zip(vals,wr)):
    ax.text(v+0.002,yi,f"{w:.0%}",va="center",ha="left",fontsize=8.5,color=INK)
ax.set_xlabel("mean cosine gap  (slogan − raw)")
ax.set_title("B · By arXiv tag  (label = % slogan-closer)",loc="left",fontweight="bold")
ax.set_xlim(0,max(vals)*1.28)
ax.spines[["top","right"]].set_visible(False)
ax.grid(axis="x",color="#EEEEEE")

# -------- Panel C: notation density vs gap --------
ax=axes[2]
col=np.where(gap>0,BLUE,VERM)
ax.scatter(nd,gap,c=col,s=26,alpha=0.8,edgecolor="white",linewidth=0.4)
# trend line
b1,b0=np.polyfit(nd,gap,1); xs=np.linspace(nd.min(),nd.max(),50)
ax.plot(xs,b0+b1*xs,color=GRAY,lw=1.6,ls="-")
ax.axhline(0,color=GRAY,lw=1,ls="--")
r=np.corrcoef(nd,gap)[0,1]
ax.set_xlabel("notation density of raw statement")
ax.set_ylabel("cosine gap  (slogan − raw)")
ax.set_title(f"C · Mechanism  (r = {r:+.2f})",loc="left",fontweight="bold")
ax.text(0.97,0.04,"symbol-dense raw →\nbigger slogan advantage",transform=ax.transAxes,
        ha="right",va="bottom",fontsize=8.5,color=GRAY)
ax.spines[["top","right"]].set_visible(False)
ax.grid(color="#EEEEEE")

fig.suptitle("Raw-LaTeX vs. slogan embedding — closeness to a natural-language query  "
             "(Qwen3-Embedding-8B, 100 theorems / 10 arXiv math tags)",
             fontsize=11.5,fontweight="bold",y=1.02)
fig.tight_layout()
fig.savefig(os.path.join(HERE,"latex_vs_slogan.png"),dpi=170,bbox_inches="tight",facecolor="white")
print("saved latex_vs_slogan.png")
