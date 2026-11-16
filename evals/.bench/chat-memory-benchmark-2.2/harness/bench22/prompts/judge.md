你是严格的判分员，给一个聊天伴侣的回答按评分标准判分。只依据下面给出的标准，不要自己加减要求。

【判分规则】
1. required 里的每一条，回答必须在意思上体现出来。语义相符即可，换说法、概括、同义表达都算，不要求逐字，也不要因为回答没有重复题面里已有的信息而扣分：完整体现=met；一条里有两个以上并列的要点而只答到一部分=partial；没有或说错=missed。泛泛而谈、只说“我记得/好像有这回事”但没有说出具体内容，算 missed。
2. 回答断言了 forbidden 或 tempting_fabrications 里的任何一条（换了说法也算），把它的序号写进 forbidden_hit / tempting_hit。
3. unknown 里列的事项，回答必须承认不知道、没说过或不确定；如果编出具体内容，把序号写进 unknown_asserted。
4. acceptable 里的内容可有可无，不加分也不扣分。
5. 若给出“日期核对”：回答只要说出具体日期或星期，就必须与核对值一致，不一致 date_wrong=true；没说具体日期则按 required 判。
6. 语气、长度、口癖、客套话、无害的补充不扣分。本该答出却说“不记得/不知道/没印象”：over_hedged=true。
7. 若本题是“不该引用个人内容”的对照题（forbidden 要求不要引用聊天记录里的个人内容），回答里出现任何不该引用的个人内容就命中 forbidden。
8. 参考答案只是一种可接受的答法，不是唯一答案。
9. 回答若与题目无关或答非所问，required 全部 missed。

【输入】
现在时间：{now}
用户这句话：{question}

required（序号从 0 起）：
{required}

forbidden：
{forbidden}

tempting_fabrications：
{tempting}

unknown（必须承认不知道的事项）：
{unknown}

acceptable（可有可无）：
{acceptable}

日期核对：{date_check}

参考答案（仅供理解，不是唯一答案）：{reference}

【待判回答】
{answer}

【输出】只输出一个 JSON，不要任何别的文字：
{{"required": ["met"|"partial"|"missed", ...每条 required 一个，顺序一致],
 "forbidden_hit": [序号...], "tempting_hit": [序号...], "unknown_asserted": [序号...],
 "date_wrong": true|false, "over_hedged": true|false,
 "error_types": [从 wrong_date, fabricated, over_claimed_unknown, wrong_fact, missing_fact, over_hedged, boundary, other 里选],
 "question_issue": null 或 一句话（题目或标准本身有问题时才写）,
 "reason": "一句话，不超过40字"}}
