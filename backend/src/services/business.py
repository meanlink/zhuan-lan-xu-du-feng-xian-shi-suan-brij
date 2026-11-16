"""专栏续读风险：训练集拟合标准化，独立留出集评估。

留出划分以身份为单位：同一真实读者名下的多个号码只进入训练或验证一侧，
避免同人样本跨侧泄漏。身份来自试验创建时冻结的台账快照，worker 从不读取
实时归属。
"""
import math
from collections import Counter
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ["sessions_14d", "completion_pct", "days_inactive", "issues_read"]
LABELS = ["14日访问次数", "阅读完成率", "连续未读天数", "已读期数"]


def metadata():
    return {
        "name": "专栏续读风险试算", "short": "reader-risk",
        "tagline": "用行为窗口解释续读风险，再试算编辑关怀的覆盖边界。",
        "client": "纸岸知识出版社 · 6人内容运营组 · 320名匿名年度专栏读者",
        "workflow": "编辑每周合并阅读日志与到期续读结果，在表格中凭访问次数选择关怀对象。",
        "pains": ["各行为量纲不同，人工排序偏向高频用户", "直接使用到期后的数据会泄漏结果", "风险阈值缺少精确率与召回率依据"],
        "upstream": "到期前14日阅读行为快照 reader_window_202611.csv",
        "downstream": "主编据验证集覆盖人数安排内容回访实验，不自动触达读者",
        "entities": ["读者行为样本", "读者身份", "续读风险试验", "编辑复核简报"],
        "dataset_name": "纸岸专栏到期前14日匿名样本",
        "columns": [{"key": "reader_id", "label": "匿名读者", "type": "string"}] + [{"key": k, "label": l, "type": "number"} for k, l in zip(FEATURES, LABELS)] + [{"key": "renewed", "label": "实际续读(1/0)", "type": "number"}],
        "parameters": [{"key": "threshold", "label": "高风险概率阈值", "type": "number", "default": 0.5, "min": 0.1, "max": 0.9}, {"key": "regularization", "label": "模型C（越小正则越强）", "type": "number", "default": 1.0, "min": 0.01, "max": 10}],
        "workbench_title": "续读风险阈值试验", "action_label": "训练并复核覆盖范围", "unit": "位读者",
        "accent": "oklch(53% 0.12 30)", "style": "editorial-press",
        "seed_story": ["08:40 编辑导入 reader_window_202611.csv 的320条匿名样本", "08:45 检查14日访问、完成率、未读天数和已读期数", "08:50 确认一位读者换号，把两个号码归并为一人；误归并的号码拆回", "09:00 以0.5风险阈值创建一次续读试验", "09:01 试验冻结身份版本，按身份分层保留25%样本做验证", "09:05 编辑比较AUC、召回率与高风险人数", "09:10 将阈值改为0.7，复核误报减少及漏报增加", "09:20 下载验证明细交主编", "10:00 管理员设置周一08:30内部复核简报"],
        "method": "实体级身份台账冻结后，按身份分层75/25留出；仅在训练集拟合StandardScaler和L2 logistic回归；目标为1-renewed；阈值只用于验证集决策。",
        "limitations": ["模拟读者行为，不能当作真实留存效果", "相关系数与模型系数不代表因果", "未包含时间外验证或干预效果评估"],
    }


def seed_records():
    rng = np.random.default_rng(1008)
    rows = []
    for i in range(320):
        sessions = int(rng.poisson(6))
        completion = float(np.clip(rng.normal(62, 21), 4, 99))
        inactive = int(rng.integers(0, 15))
        issues = int(rng.integers(1, 25))
        logit = -0.5 - 0.20 * sessions - 0.025 * (completion - 50) + 0.27 * inactive - 0.035 * issues
        risk = 1 / (1 + math.exp(-logit))
        rows.append({"reader_id": f"RD-{i+1:04}", "sessions_14d": sessions, "completion_pct": round(completion, 1), "days_inactive": inactive, "issues_read": issues, "renewed": int(rng.random() >= risk)})
    return rows


def _identity_labels(records, snapshot):
    """Map every row to the identity group frozen in the snapshot.

    A snapshot bound to the dataset defines membership; numbers missing from it
    (or a job without a snapshot) fall back to the number itself, so a person
    is never silently merged at analysis time.
    """
    mapping = (snapshot or {}).get('numbers') or {}
    labels = []
    unknown = set()
    for row in records:
        number = str(row.get('reader_id', '')).strip()
        group = mapping.get(number)
        if group is None:
            group = f'NUMBER:{number}'
            if number:
                unknown.add(number)
        labels.append(group)
    return labels, sorted(unknown)


def analyze(records, params, identity_snapshot=None):
    try:
        threshold = float(params.get("threshold", 0.5))
        c_value = float(params.get("regularization", 1.0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("风险阈值与模型C须为有效数值。") from exc
    if not 0.1 <= threshold <= 0.9 or not 0.01 <= c_value <= 10:
        raise ValueError("风险阈值须为0.1~0.9，模型C须为0.01~10。")
    if len(records) < 40:
        raise ValueError("至少需要40条完整样本，以保留独立验证集。")
    try:
        x = np.asarray([[float(row[k]) for k in FEATURES] for row in records])
        renewed = np.asarray([float(row["renewed"]) for row in records])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("行为字段与续读标签必须完整且为数值。") from exc
    if not np.isfinite(x).all() or not np.isin(renewed, [0, 1]).all() or (x < 0).any() or (x[:, 1] > 100).any():
        raise ValueError("行为值必须非负且有限，完成率0~100，续读标签只能为0/1。")
    y = 1 - renewed.astype(int)
    counts = np.bincount(y, minlength=2)
    if counts.min() < 8:
        raise ValueError("续读与未续读两类各至少8条样本。")
    person_labels, unknown = _identity_labels(records, identity_snapshot)
    if len(set(person_labels)) < 20:
        raise ValueError("按身份归并后不足20位独立读者，无法保留独立验证集。")
    # Stratify by person, not by row: numbers of one person must stay on one
    # side of the split. Each identity gets a label stratum from its own
    # renewal mix so both sides still see renewed and not-renewed people.
    unique_people = sorted(set(person_labels))
    people_rows = {}
    for row_index, person in enumerate(person_labels):
        people_rows.setdefault(person, []).append(row_index)
    person_strata = {}
    for person in unique_people:
        likeliness = float(np.mean([y[i] for i in people_rows[person]]))
        person_strata[person] = 2 if likeliness > 0.66 else (0 if likeliness < 0.34 else 1)
    strata = np.asarray([person_strata[p] for p in unique_people])
    # A stratum needs >=2 identities for train_test_split to keep it on both sides.
    counts_by_stratum = Counter(person_strata.values())
    if any(n < 2 for n in counts_by_stratum.values()):
        persons_train, persons_valid = train_test_split(
            np.asarray(unique_people), test_size=0.25, random_state=42)
    else:
        persons_train, persons_valid = train_test_split(
            np.asarray(unique_people), test_size=0.25, stratify=strata, random_state=42)
    train_set, valid_set = set(persons_train.tolist()), set(persons_valid.tolist())
    train = np.asarray([i for i, label in enumerate(person_labels) if label in train_set])
    valid = np.asarray([i for i, label in enumerate(person_labels) if label in valid_set])
    if len(train) == 0 or len(valid) == 0:
        raise ValueError("身份划分未能形成训练与验证两侧，请检查号码归属。")
    if len(set(y[train])) < 2:
        raise ValueError("训练侧只有单一续读结果，无法拟合；请补充样本或检查归并。")
    model = make_pipeline(StandardScaler(), LogisticRegression(C=c_value, max_iter=1000, random_state=42))
    model.fit(x[train], y[train])
    probability = model.predict_proba(x[valid])[:, 1]
    # The review target is a reader, not a login number: aggregate each
    # person's numbers in the validation side to one decision so a merged
    # reader is counted once.
    by_person = {}
    for position, row_index in enumerate(valid):
        person = person_labels[int(row_index)]
        entry = by_person.setdefault(person, {'numbers': [], 'probability': 0.0, 'label': 0})
        entry['numbers'].append(str(records[int(row_index)].get('reader_id', f'row-{int(row_index)+1}')))
        entry['probability'] = max(entry['probability'], float(probability[position]))
        entry['label'] = max(entry['label'], int(y[int(row_index)]))
    person_order = sorted(by_person, key=lambda p: -by_person[p]['probability'])
    person_probability = np.asarray([by_person[p]['probability'] for p in person_order])
    person_actual = np.asarray([by_person[p]['label'] for p in person_order])
    person_decision = (person_probability >= threshold).astype(int)
    auc = float(roc_auc_score(person_actual, person_probability)) if len(set(person_actual.tolist())) > 1 else float('nan')
    precision = float(precision_score(person_actual, person_decision, zero_division=0))
    recall = float(recall_score(person_actual, person_decision, zero_division=0))
    tn, fp, fn, tp = [int(v) for v in confusion_matrix(person_actual, person_decision, labels=[0, 1]).ravel()]
    coefficients = model[-1].coef_[0]
    rows = [{"identity": person,
             "numbers": "、".join(sorted(by_person[person]['numbers'])),
             "risk_pct": round(by_person[person]['probability'] * 100, 2),
             "decision": "建议编辑复核" if person_decision[j] else "维持观察",
             "actual": "未续读" if person_actual[j] else "已续读"}
            for j, person in enumerate(person_order)]
    strongest = int(np.argmax(np.abs(coefficients)))
    train_people, valid_people = set(person_labels[i] for i in train), set(person_labels[i] for i in valid)
    overlap = train_people & valid_people
    merged_people = sum(1 for person in unique_people if len(people_rows[person]) > 1)
    version = (identity_snapshot or {}).get('version')
    basis = (f'身份版本 v{version}' if version is not None
             else '未冻结身份（按号码各自独立）')
    return {
        "summary": f"训练{len(train)}条、独立验证{len(valid)}条；阈值{threshold:.2f}下有{int(person_decision.sum())}位读者进入编辑复核。",
        "metrics": [{"label": "验证AUC", "value": round(auc, 4) if np.isfinite(auc) else None},
                    {"label": "风险召回率", "value": round(recall * 100, 2), "unit": "%"},
                    {"label": "风险精确率", "value": round(precision * 100, 2), "unit": "%"},
                    {"label": "验证集高风险", "value": int(person_decision.sum()), "unit": "人"}],
        "table": {"columns": [{"key": "identity", "label": "身份编号"},
                              {"key": "numbers", "label": "验证侧号码"},
                              {"key": "risk_pct", "label": "风险概率(%)"},
                              {"key": "decision", "label": "阈值决策"},
                              {"key": "actual", "label": "留出集实际结果"}], "rows": rows},
        "chart": {"type": "bar", "labels": LABELS, "series": [{"name": "标准化log-odds系数", "values": [round(float(v), 4) for v in coefficients]}]},
        "findings": [f"验证混淆矩阵（按读者计）：命中未续读{tp}、误报{fp}、漏报{fn}、正确排除{tn}。",
                     f"绝对系数最大的特征为{LABELS[strongest]}（{float(coefficients[strongest]):.3f}）；正值意味着更高未续读风险。",
                     f"验证准确率{accuracy_score(person_actual, person_decision)*100:.1f}%；阈值变更影响覆盖边界，不改变AUC。",
                     f"身份依据：{basis}；训练侧{len(train_people)}人、验证侧{len(valid_people)}人，"
                     f"跨侧同人{len(overlap)}人，其中多号码身份{merged_people}个。",
                     "以身份而非号码划分留出集，同一人的多个号码只进入训练或验证一侧；"
                     "验证侧同一人的号码合并为一条复核记录。"],
        "method": metadata()["method"] + " 留出以身份为单位划分。",
        "identity": {"version": version, "fingerprint": (identity_snapshot or {}).get('fingerprint'),
                     "basis": basis, "train_people": len(train_people),
                     "valid_people": len(valid_people), "merged_people": merged_people,
                     "cross_side_people": len(overlap), "unknown_numbers": unknown},
        "warnings": ["风险排序供编辑复核使用，不能据此断言某项行为导致未续读。"],
    }
