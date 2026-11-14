from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MultipleLocator


# ============================================================
# 1. 输出路径
# ============================================================
OUTPUT_DIR = Path(
    r"D:\HuaweiMoveData\Users\86185\Documents\小样本\outputs\figures"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. 期刊绘图格式
# ============================================================
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix",

    "font.size": 8,
    "axes.labelsize": 8.5,
    "xtick.labelsize": 7.3,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,

    "axes.linewidth": 0.8,
    "lines.linewidth": 1.5,
    "lines.markersize": 5.5,

    "pdf.fonttype": 42,
    "ps.fonttype": 42,

    "savefig.facecolor": "white",
    "figure.facecolor": "white",
})


# ============================================================
# 3. 实验数据
# ============================================================

# 子图(a)：每个batch覆盖的类别数量
coverage_x = np.array([1, 2, 3, 4])

coverage_acc = np.array([
    70.00,
    71.67,
    72.33,
    85.00
])

coverage_f1 = np.array([
    69.32,
    71.12,
    72.21,
    84.76
])

coverage_labels = [
    "1 class\n32/0/0/0",
    "2 classes\n16/16/0/0",
    "3 classes\n11/11/10/0",
    "4 classes\n8/8/8/8",
]


# 子图(b)：类别不均衡程度
imbalance_x = np.array([0, 1, 2, 3])

imbalance_acc = np.array([
    85.00,   # Balanced
    75.00,   # Mild
    73.33,   # Moderate
    72.33,   # Severe
])

imbalance_f1 = np.array([
    84.76,
    74.39,
    72.82,
    71.37,
])

# 自然比例单独放置，不与前面的曲线连接
natural_x = 4.5
natural_acc = 75.33
natural_f1 = 74.69

imbalance_ticks = [0, 1, 2, 3, natural_x]

imbalance_labels = [
    "Balanced\n8/8/8/8",
    "Mild\n12/8/6/6",
    "Moderate\n16/8/4/4",
    "Severe\n20/6/3/3",
    "Natural\n6/10/12/4",
]


# ============================================================
# 4. 颜色和图形
# ============================================================
ACC_COLOR = "#2878B5"
F1_COLOR = "#D95F02"
GRID_COLOR = "#D8D8D8"
HIGHLIGHT_COLOR = "#F3E7C9"

# 约180 mm宽，适合作为双栏figure*
fig, axes = plt.subplots(
    1,
    2,
    figsize=(7.1, 3.15),
    sharey=True
)


# ============================================================
# 5. 子图(a)：类别覆盖数量
# ============================================================
ax = axes[0]

# 突出四类均衡配置
ax.axvspan(
    3.72,
    4.28,
    color=HIGHLIGHT_COLOR,
    alpha=0.55,
    zorder=0
)

line_acc, = ax.plot(
    coverage_x,
    coverage_acc,
    color=ACC_COLOR,
    marker="o",
    markerfacecolor="white",
    markeredgewidth=1.2,
    label="Recording Accuracy",
    zorder=3
)

line_f1, = ax.plot(
    coverage_x,
    coverage_f1,
    color=F1_COLOR,
    linestyle="--",
    marker="s",
    markerfacecolor="white",
    markeredgewidth=1.2,
    label="Recording Macro-F1",
    zorder=3
)

# 数值标注：Accuracy在上，Macro-F1在下
for x, acc, f1 in zip(coverage_x, coverage_acc, coverage_f1):
    ax.annotate(
        f"{acc:.2f}",
        xy=(x, acc),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=6.8,
        color=ACC_COLOR
    )

    ax.annotate(
        f"{f1:.2f}",
        xy=(x, f1),
        xytext=(0, -9),
        textcoords="offset points",
        ha="center",
        va="top",
        fontsize=6.8,
        color=F1_COLOR
    )

ax.set_xticks(coverage_x)
ax.set_xticklabels(coverage_labels)
ax.set_xlabel("Number of classes covered per mini-batch")
ax.set_ylabel("Performance (%)")
ax.set_xlim(0.65, 4.35)


# ============================================================
# 6. 子图(b)：类别不均衡程度
# ============================================================
ax = axes[1]

# 突出四类均衡配置
ax.axvspan(
    -0.28,
    0.28,
    color=HIGHLIGHT_COLOR,
    alpha=0.55,
    zorder=0
)

ax.plot(
    imbalance_x,
    imbalance_acc,
    color=ACC_COLOR,
    marker="o",
    markerfacecolor="white",
    markeredgewidth=1.2,
    zorder=3
)

ax.plot(
    imbalance_x,
    imbalance_f1,
    color=F1_COLOR,
    linestyle="--",
    marker="s",
    markerfacecolor="white",
    markeredgewidth=1.2,
    zorder=3
)

# 自然比例使用空心菱形，且不与曲线连接
ax.scatter(
    natural_x,
    natural_acc,
    s=38,
    marker="D",
    facecolors="white",
    edgecolors=ACC_COLOR,
    linewidths=1.2,
    zorder=4
)

ax.scatter(
    natural_x,
    natural_f1,
    s=38,
    marker="D",
    facecolors="white",
    edgecolors=F1_COLOR,
    linewidths=1.2,
    zorder=4
)

# 人为设置的四种均衡程度
for x, acc, f1 in zip(
    imbalance_x,
    imbalance_acc,
    imbalance_f1
):
    ax.annotate(
        f"{acc:.2f}",
        xy=(x, acc),
        xytext=(0, 6),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=6.8,
        color=ACC_COLOR
    )

    ax.annotate(
        f"{f1:.2f}",
        xy=(x, f1),
        xytext=(0, -9),
        textcoords="offset points",
        ha="center",
        va="top",
        fontsize=6.8,
        color=F1_COLOR
    )

# 自然比例数值
ax.annotate(
    f"{natural_acc:.2f}",
    xy=(natural_x, natural_acc),
    xytext=(0, 7),
    textcoords="offset points",
    ha="center",
    va="bottom",
    fontsize=6.8,
    color=ACC_COLOR
)

ax.annotate(
    f"{natural_f1:.2f}",
    xy=(natural_x, natural_f1),
    xytext=(0, -10),
    textcoords="offset points",
    ha="center",
    va="top",
    fontsize=6.8,
    color=F1_COLOR
)

# 使用竖直虚线将自然比例与人为不均衡配置分开
ax.axvline(
    x=3.75,
    color="#999999",
    linestyle=":",
    linewidth=0.8,
    zorder=1
)

ax.set_xticks(imbalance_ticks)
ax.set_xticklabels(imbalance_labels)
ax.set_xlabel("Mini-batch class composition")
ax.set_xlim(-0.45, 4.85)


# ============================================================
# 7. 两幅子图的公共格式
# ============================================================
for ax in axes:
    ax.set_ylim(65, 90)
    ax.yaxis.set_major_locator(MultipleLocator(5))

    ax.grid(
        axis="y",
        color=GRID_COLOR,
        linestyle="--",
        linewidth=0.6,
        alpha=0.75
    )

    ax.tick_params(
        axis="both",
        direction="out",
        length=3,
        width=0.8
    )

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# 子图编号放在左下方
axes[0].text(
    0.0,
    -0.32,
    "(a)",
    transform=axes[0].transAxes,
    ha="left",
    va="top",
    fontsize=8.5
)

axes[1].text(
    0.0,
    -0.32,
    "(b)",
    transform=axes[1].transAxes,
    ha="left",
    va="top",
    fontsize=8.5
)


# 公共图例
fig.legend(
    handles=[line_acc, line_f1],
    labels=[
        "Recording Accuracy",
        "Recording Macro-F1"
    ],
    loc="upper center",
    bbox_to_anchor=(0.5, 1.01),
    ncol=2,
    frameon=False,
    columnspacing=1.8,
    handlelength=2.5
)


# 调整间距
fig.subplots_adjust(
    left=0.085,
    right=0.995,
    bottom=0.28,
    top=0.84,
    wspace=0.18
)


# ============================================================
# 8. 保存PDF和PNG
# ============================================================
pdf_path = OUTPUT_DIR / "batch_composition.pdf"
png_path = OUTPUT_DIR / "batch_composition.png"

fig.savefig(
    pdf_path,
    format="pdf",
    bbox_inches="tight",
    pad_inches=0.03
)

fig.savefig(
    png_path,
    format="png",
    dpi=600,
    bbox_inches="tight",
    pad_inches=0.03
)

plt.show()

print(f"PDF saved to: {pdf_path}")
print(f"PNG saved to: {png_path}")