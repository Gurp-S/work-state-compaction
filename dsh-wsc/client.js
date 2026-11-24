window.__ModuleLoader__.load({
  id: '@xeyo/dsh-wsc',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const NS = 'wsc'
    const ENTRY = 'wsc-config'

    const DICT = {
      en: {
        nav: 'Context compaction',
        title: 'Context compaction',
        intro: 'WSC replaces the shipped summarizer inside the active agent preset. Values below are live.',
        mode: 'Mode',
        modeActive: 'Active',
        modeShadow: 'Shadow (measure only)',
        modeOff: 'Off',
        secTrigger: 'Compaction trigger',
        secCheckpoint: 'Checkpoint content',
        secExtraction: 'Extraction',
        secTools: 'Tools',
        capacityPercent: 'Window share (%)',
        effectiveWindow: 'Working window (tokens, 0 = model window)',
        warn: 'Warning threshold',
        force: 'Forced compaction',
        minReclaim: 'Minimum reclaim (%)',
        ledgerCap: 'Ledger byte cap (0 = unlimited)',
        ledgerDenoise: 'Fold superseded ledger entries',
        evidenceRows: 'Evidence index rows (0 = off)',
        latest: 'Pin the latest request',
        recent: 'Recent changes and checks',
        verify: 'Entry verification',
        verifyLiteral: 'Literal anchors (default)',
        verifyCite: 'Citation only',
        verifyQuote: 'Verbatim quote',
        segment: 'Extraction segment (bytes)',
        entries: 'Entries per segment',
        effort: 'Extraction reasoning effort',
        effortInherit: 'Inherit session',
        effortOff: 'Off',
        effortLow: 'Low',
        effortMedium: 'Medium',
        effortHigh: 'High',
        verifyHint: 'Literal anchors: numbers, paths and identifiers in an entry must appear in the cited message, otherwise the entry is rejected. This blocks fabricated values but cannot prove a prose rationale. Citation only checks that the cited message exists. Verbatim quote requires exact supporting text; it is the strongest check and costs more output tokens.',
        denoise: 'Denoise tool output',
        evidence: 'Register the history retrieval tool',
        hint: 'Thresholds are shares of the capacity. A warning-triggered compaction is skipped when it would reclaim less than the minimum.',
        unavailable: 'This profile does not serve the WSC configuration.',
        saved: 'Saved',
        failed: 'Not saved',
      },
      zh: {
        nav: '上下文压缩',
        title: '上下文压缩',
        intro: 'WSC 替换当前 agent preset 里的摘要器，下面的值即时生效。',
        mode: '模式',
        modeActive: '启用',
        modeShadow: '影子（只测量）',
        modeOff: '关闭',
        secTrigger: '压缩触发',
        secCheckpoint: '检查点内容',
        secExtraction: '抽取',
        secTools: '工具',
        capacityPercent: '窗口占比（%）',
        effectiveWindow: '有效窗口（token，0 = 模型窗口）',
        warn: '警告阈值',
        force: '强制压缩阈值',
        minReclaim: '最小回收比例（%）',
        ledgerCap: '账本字节上限（0 = 不限）',
        ledgerDenoise: '折叠账本旧版本',
        evidenceRows: '证据索引行数（0 = 关闭）',
        latest: '置顶最新请求',
        recent: '最近改动与检查',
        verify: '条目校验',
        verifyLiteral: '字面锚点（默认）',
        verifyCite: '仅校验引用',
        verifyQuote: '逐字引文',
        segment: '抽取分段（字节）',
        entries: '每段条目上限',
        effort: '抽取推理强度',
        effortInherit: '继承会话',
        effortOff: '关闭',
        effortLow: '低',
        effortMedium: '中',
        effortHigh: '高',
        verifyHint: '字面锚点：条目里的数字、路径、标识符必须出现在被引用的消息里，否则丢弃；能挡住编造值，但不能证明散文式理由。仅校验引用：只要求引用存在，最便宜。逐字引文：模型必须给出原文，引擎逐字核对，最强但输出更多。',
        denoise: '工具输出去噪',
        evidence: '注册历史回读工具',
        hint: '阈值按窗口容量的比例计算；提示触发的压缩若回收量低于最小比例，会被跳过。',
        unavailable: '当前 profile 没有提供 WSC 配置。',
        saved: '已保存',
        failed: '未保存',
      },
    }

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

    const readSnapshot = (form) => {
      try {
        return form === undefined ? undefined : form.getSnapshot()
      } catch {
        return undefined
      }
    }

    const styles = {
      page: { padding: '8px 0 24px', display: 'flex', flexDirection: 'column', gap: 4, maxWidth: 640 },
      title: { color: 'var(--dsw-alias-label-primary)', fontSize: 16, fontWeight: 500, margin: '0 0 4px' },
      intro: { color: 'var(--dsw-alias-label-secondary)', fontSize: 13, lineHeight: '20px', margin: '0 0 12px' },
      row: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        padding: '10px 0',
        borderBottom: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.18))',
      },
      label: { color: 'var(--dsw-alias-label-primary)', fontSize: 14 },
      section: {
        color: 'var(--dsw-alias-label-primary)',
        fontSize: 13,
        fontWeight: 600,
        margin: '18px 0 2px',
      },
      hint: { color: 'var(--dsw-alias-label-secondary)', fontSize: 12, lineHeight: '18px', marginTop: 12 },
      control: {
        color: 'var(--dsw-alias-label-primary)',
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.3))',
        borderRadius: 6,
        padding: '4px 8px',
        fontSize: 13,
        minWidth: 160,
      },
      number: {
        color: 'var(--dsw-alias-label-primary)',
        background: 'var(--dsw-alias-bg-layer-2)',
        border: '1px solid var(--dsw-alias-border-l1, rgba(128,128,128,0.3))',
        borderRadius: 6,
        padding: '4px 8px',
        fontSize: 13,
        width: 96,
        textAlign: 'right',
      },
    }

    function Row({ label, children }) {
      return h('div', { style: styles.row }, h('span', { style: styles.label }, label), children)
    }

    function Page(props) {
      const form = props.form
      const t = props.t
      const [snapshot, setSnapshot] = React.useState(() => readSnapshot(form))
      const [status, setStatus] = React.useState('')

      React.useEffect(() => {
        if (form === undefined || typeof form.subscribe !== 'function') return undefined
        return form.subscribe(() => setSnapshot(readSnapshot(form)))
      }, [form])

      if (snapshot === undefined || snapshot.value === undefined) {
        return h('div', { style: styles.page }, h('div', { style: styles.intro }, t('unavailable')))
      }

      const value = snapshot.value
      const write = (key, next) => {
        if (form === undefined || typeof form.mutate !== 'function') return
        setStatus('')
        Promise.resolve(form.mutate([{ op: 'set', path: [key], value: next }]))
          .then(() => setStatus('saved'))
          .catch(() => setStatus('failed'))
      }

      const mode = h(
        'select',
        { style: styles.control, value: value.mode ?? 'active', onChange: (event) => write('mode', event.target.value) },
        h('option', { value: 'active' }, t('modeActive')),
        h('option', { value: 'shadow' }, t('modeShadow')),
        h('option', { value: 'off' }, t('modeOff')),
      )

      const verification = h(
        'select',
        {
          style: styles.control,
          value: value.nosigVerification ?? 'literal',
          onChange: (event) => write('nosigVerification', event.target.value),
        },
        h('option', { value: 'literal' }, t('verifyLiteral')),
        h('option', { value: 'cite' }, t('verifyCite')),
        h('option', { value: 'quote' }, t('verifyQuote')),
      )

      const number = (key, min, max, step = 0.01, disabled = false) =>
        h('input', {
          style: styles.number,
          type: 'number',
          min,
          max,
          step,
          disabled,
          defaultValue: value[key],
          onBlur: (event) => {
            const parsed = Number(event.target.value)
            if (Number.isFinite(parsed)) write(key, clamp(parsed, min, max))
          },
        })

      const percent = (key, fallback) =>
        h('input', {
          style: styles.number,
          type: 'number',
          min: 0,
          max: 100,
          step: 1,
          defaultValue: Math.round((value[key] ?? fallback) * 100),
          onBlur: (event) => {
            const parsed = Number(event.target.value)
            if (Number.isFinite(parsed)) write(key, clamp(parsed, 0, 100) / 100)
          },
        })

      const check = (key) =>
        h('input', {
          type: 'checkbox',
          checked: value[key] !== false,
          onChange: (event) => write(key, event.target.checked),
        })

      const effort = h(
        'select',
        {
          style: styles.control,
          value: value.nosigReasoningEffort ?? '',
          onChange: (event) => write('nosigReasoningEffort', event.target.value),
        },
        h('option', { value: '' }, t('effortInherit')),
        h('option', { value: 'off' }, t('effortOff')),
        h('option', { value: 'low' }, t('effortLow')),
        h('option', { value: 'medium' }, t('effortMedium')),
        h('option', { value: 'high' }, t('effortHigh')),
      )

      return h(
        'div',
        { style: styles.page },
        h('h2', { style: styles.title }, t('title')),
        h('p', { style: styles.intro }, t('intro')),
        h(Row, { label: t('mode') }, mode),

        h('h3', { style: styles.section }, t('secTrigger')),
        h(Row, { label: t('effectiveWindow') }, number('effectiveWindowTokens', 0, 1000000, 1000)),
        h(Row, { label: t('capacityPercent') }, number('capacityPercent', 1, 100, 1)),
        h(Row, { label: t('warn') }, number('warnRatio', 0.5, 0.95)),
        h(Row, { label: t('force') }, number('forceRatio', 0.5, 0.99)),
        h(Row, { label: t('minReclaim') }, percent('minReclaimRatio', 0.15)),

        h('h3', { style: styles.section }, t('secCheckpoint')),
        h(Row, { label: t('ledgerCap') }, number('ledgerCapBytes', 0, 65536, 1)),
        h(Row, { label: t('ledgerDenoise') }, check('ledgerDenoise')),
        h(Row, { label: t('evidenceRows') }, number('evidenceIndexRows', 0, 20, 1)),
        h(Row, { label: t('latest') }, check('passageLatest')),
        h(Row, { label: t('recent') }, check('passageRecent')),

        h('h3', { style: styles.section }, t('secExtraction')),
        h(Row, { label: t('verify') }, verification),
        h(Row, { label: t('segment') }, number('nosigSegmentBytes', 4096, 200000, 1)),
        h(Row, { label: t('entries') }, number('nosigEntryCap', 1, 50, 1)),
        h(Row, { label: t('effort') }, effort),

        h('h3', { style: styles.section }, t('secTools')),
        h(Row, { label: t('denoise') }, check('denoise')),
        h(Row, { label: t('evidence') }, check('evidenceTool')),

        h('p', { style: styles.hint }, t('verifyHint')),
        h('p', { style: styles.hint }, t('hint')),
        status === '' ? null : h('p', { style: styles.hint }, t(status)),
      )
    }

    return {
      inject: ['slots', 'locale', 'configForms'],
      apply(ctx) {
        ctx.effect(() => ctx.locale.register(NS, DICT), 'wsc: dictionaries')
        const t = ctx.locale.bind(NS)

        ctx.slots.inject('settings.section', () =>
          ctx.slots.register(
            {
              name: 'settings.section',
              id: 'wsc',
              order: 25,
              label: () => t('nav'),
              locale: NS,
              inject: () => {
                let form
                try {
                  form = ctx.configForms.get(ENTRY)
                } catch {
                  form = undefined
                }
                return { form, t }
              },
            },
            Page,
          ),
        )
      },
    }
  },
})
