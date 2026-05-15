# 铁路双轨寻路算法设计规约 (Transfer Routing Routing Specification)

## 一、 问题建模 (Problem Modeling)

将包含时间属性的铁路网寻路问题，解耦为空间拓扑可达性（Spatial Reachability）**与**时序因果合法性（Temporal Causality）两个正交维度。

### 1. 空间与时间映射模型

- **车站空间 $\mathcal{S}$**：所有物理车站的集合。引入同城关系映射 $\mathcal{C}(s)$，表示与车站 $s$ 属于同一城市群的车站及其通勤耗时。

- **车次空间 $\mathcal{T}$**：所有具体执行车次（Trip）的集合。

- **绝对时间标量**：将发车与到达时间转换为相对查询基准日的绝对分钟数 $T_{abs}$，以消除跨日计算的复杂度：

  $$ T_{abs} = \text{DayOffset} \times 1440 + \text{Hour} \times 60 + \text{Minute} $$

### 2. 核心倒排索引结构

系统不使用传统的图节点指针，而是维护以下三个时间复杂度为 $O(1)$ 的映射函数：

- **$S2T(s)$**：输入车站，返回停靠该站的**车次集合** (Hash Set)。
- **$T2S(t)$**：输入车次，返回该车次依序停靠的**车站序列** (Array)。
- **$Timetable(t, s)$**：输入车次与车站，返回绝对时间元组 $(arr\_time, dep\_time)$。

------

## 二、 算法思路 (Algorithm Logic)

本算法采用 **Filter-and-Refine（过滤与精炼）** 范式，通过空间降维解决图搜索的组合爆炸问题。

1. **阶段一：空间膨胀与拓扑降维 (Filter)**

   放弃对“车站节点”的深度优先遍历。将起点和终点的一阶辐射站集合向上映射到“车次空间”，利用现代编程语言底层的哈希集合求交运算（Set Intersection），在 $O(1)$ 或极短时间内找出所有物理上连通的粗糙解。支持通过“同城膨胀”将同城多站视为等效换乘群。

2. **阶段二：链式时序精炼 (Refine)**

   物理拓扑连通不代表时间合法。对粗糙解进行严格的方向校验（防逆行）与时序校验。利用预先排序的车站发车时刻表，将传统的嵌套循环比对，转化为时间复杂度为 $O(\log N)$ 的**二分查找（Binary Search）**，快速确定后序车次的合法接续边界。

------

## 三、 算法步骤 (Algorithm Steps)

设用户输入为：起点 $S_{start}$，终点 $S_{end}$，最早出发时间 $Time_{depart}$。

### 0. 预处理：同城拓扑膨胀

获取起点和终点的等效同城站集合：

$$ E_{start} = \{ S_{start} \} \cup keys(\mathcal{C}(S_{start})) $$

$$ E_{end} = \{ S_{end} \} \cup keys(\mathcal{C}(S_{end})) $$

### 1. 零次换乘（直达）

1. **空间求交**：遍历 $E_{start}$ 和 $E_{end}$ 的组合，计算直达车次集合：

   $$ T_{direct} = \bigcup_{s \in E_{start}, e \in E_{end}} (S2T(s) \cap S2T(e)) $$

2. **时序验证**：遍历 $T_{direct}$ 中的车次 $t$。若满足 $t$ 在起点的 $dep\_time \ge Time_{depart}$，且 $dep\_time < t$ 在终点的 $arr\_time$（物理方向正确），则记为有效直达方案。

### 2. 一次换乘（两段行程）

1. **空间求交（找站）**：

   计算起点侧一阶辐射站 $V_S$ 与终点侧一阶辐射站 $V_T$。

   $$ M_{candidates} = Expand(V_S) \cap Expand(V_T) $$

   得到候选换乘对集合（包含同站与同城跨站对）。

2. **时序验证与二分查找**：

   对于每个换乘对 $(m_{in}, m_{out})$，计算其交通耗时 $\Delta t$。

   获取合法前序车次集合 $T_1$ 和后序车次集合 $T_2$。

   对于每个 $t_1 \in T_1$：

   - 计算最早接续时间边界：$Limit = Timetable(t_1, m_{in}).arr\_time + \Delta t$。
   - 在 $m_{out}$ 的预排序发车数组中，二分查找第一个发车时间 $\ge Limit$ 的索引。其后的所有属于 $T_2$ 的车次，均与 $t_1$ 构成合法的一次换乘方案。

### 3. 两次换乘（三段行程）

1. **空间求交（找车）**：

   将 $V_S$ 和 $V_T$ 向上映射回车次空间，得到候选的中间车次集合：

   $$ T_{mid} = \left( \bigcup_{v \in V_S} S2T(v) \right) \cap \left( \bigcup_{v \in V_T} S2T(v) \right) $$

2. **拓扑回溯**：

   遍历 $t_{mid}$，向下提取第一换乘站 $m_1$ 与第二换乘站 $m_2$ 的候选集。

   进行**防逆行校验**：在 $T2S(t_{mid})$ 序列中，$m_1$ 的索引必须严格小于 $m_2$ 的索引。

3. **链式时序验证**：

   计算第一段的接续边界 $Limit_1$，校验是否能赶上 $t_{mid}$。

   若能赶上，利用 $t_{mid}$ 到达 $m_2$ 的时间计算第二段接续边界 $Limit_2$。

   再次利用二分查找，快速圈定合法的尾段车次 $t_2$。

------

## 四、 实现细节 (Implementation Details)

在代码落地时，需在内存中构建以下核心数据结构，建议使用强类型语言（C++, Rust, Go, Java）以保证极速的集合运算：

Python

```
# 数据结构类型注解 (Type Hints for implementation)

# 1. 倒排索引：采用连续数组而非链表以优化 Cache 命中率
S2T: Dict[int, Set[int]]      # StationID -> Set<TripID>
T2S: Dict[int, List[int]]     # TripID -> List<StationID> (严格按停靠顺序)

# 2. 时序字典：(车次, 车站) 复合主键
Timetable: Dict[Tuple[int, int], TimeRecord] 
# TimeRecord = { arr_time: int, dep_time: int }

# 3. 预排序发车索引 (SDI - Station Departure Index)
# 核心结构，专门服务于二分查找
SDI: Dict[int, List[DepartureEvent]] 
# DepartureEvent = { trip_id: int, dep_time: int }
# 必须保证 List 内部按照 dep_time 升序排列

# 4. 同城映射组
CityGroup: Dict[int, Dict[int, int]]
# 示例：CityGroup[北京南][北京西] = 50 (分钟)
```

------

## 五、 注意事项 (Caveats & Engineering Notes)

1. **位图优化 (BitMap Acceleration)**

   底层 `Set[int]` 极力推荐使用位图（如 Roaring Bitmap 或 `std::bitset`）实现。因为两次换乘中计算 $C_S \cap C_T$ 时，是对全网的车次 ID 进行求交，位图的按位与 (`&`) 运算可以将此类操作压制在纳秒级。

2. **幽灵逆行过滤 (Phantom Reverse-Routing)**

   在利用倒排索引时，集合丢失了序列信息。必须在拓扑回溯阶段严格检查 $T2S$ 数组中的索引顺序。如果 $S \xrightarrow{t} E$，但在 $t$ 的停靠列表中 $E$ 出现在 $S$ 之前，这属于物理逆行，必须立刻 `continue` 剪枝。

3. **多目标帕累托排序 (Pareto Front Sorting)**

   寻路引擎会产生极其庞大的有效解（尤其是 2 次换乘）。在 `SAVE_PATH` 阶段，不应直接保留所有方案。应建立一个定长优先队列（Min-Heap），根据成本函数 $Cost = \alpha \cdot \text{总耗时} + \beta \cdot \text{总距离} + \gamma \cdot \text{换乘等待惩罚}$ 动态淘汰劣质解，最终仅返回 Top-K（如前 50 条）最优路线给调用方。

4. **最小换乘时间防越界**

   在处理同城跨站换乘（如 50 分钟地铁）时，务必将该耗时作为动态的 $\Delta t_{min}$ 注入到二分查找的 $Limit$ 边界计算中，不可硬编码为统一的同站换乘时间（如 20 分钟）。