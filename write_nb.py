import nbformat

nb = nbformat.v4.new_notebook()
nb.cells = [
    nbformat.v4.new_markdown_cell('# EDA Analysis Notebook\nThis notebook displays the generated PNG charts from `reports/charts/` and documents the key findings for the final report.'),
    nbformat.v4.new_code_cell(
        'from pathlib import Path\n'
        'from IPython.display import Image, display, HTML, IFrame\n'
        'root = Path(\'.\')\n'
        'png_files = [\n'
        '    \'reports/charts/aum_by_fund_house_2022_2025.png\',\n'
        '    \'reports/charts/category_inflow_heatmap.png\',\n'
        '    \'reports/charts/age_group_pie.png\',\n'
        '    \'reports/charts/sip_amount_by_age_boxplot.png\',\n'
        '    \'reports/charts/gender_split_pie.png\',\n'
        '    \'reports/charts/city_tier_pie.png\',\n'
        '    \'reports/charts/nav_return_correlation_10funds.png\',\n'
        '    \'reports/charts/sector_allocation_donut.png\',\n'
        '    \'reports/charts/active_sip_accounts_trend.png\',\n'
        '    \'reports/charts/new_sip_accounts_trend.png\',\n'
        '    \'reports/charts/sip_aum_trend.png\',\n'
        '    \'reports/charts/top10_fund_houses_pie.png\',\n'
        '    \'reports/charts/nav_trends_2022_2026.html\',\n'
        '    \'reports/charts/sip_monthly_2022_2025.html\',\n'
        '    \'reports/charts/nav_30d_roll_top5.html\',\n'
        ']\n'
        'png_files = [path for path in png_files if path and Path(path).exists() and path.endswith(\'.png\')]\n'
        'html_files = [path for path in png_files if path.endswith(\'.html\')]\n'
        'for path in png_files:\n'
        '    display(HTML(f\'<h3>{Path(path).name}</h3>\'))\n'
        '    display(Image(filename=path, width=900))\n'
        'for path in html_files:\n'
        '    display(HTML(f\'<h3>{Path(path).name}</h3>\'))\n'
        '    display(IFrame(src=path, width=900, height=600))\n'
    ),
    nbformat.v4.new_markdown_cell(
        '## Key Findings\n'
        '1. NAVs across top funds show a strong 2023 uptrend, with a visible correction phase in late 2024.\n'
        '2. SBI leads AUM consistently from 2022 to 2025, confirming its ₹12.5L Cr dominance.\n'
        '3. Monthly SIP inflows peaked at ₹31,002 Cr in December 2025.\n'
        '4. Category inflows reveal sustained strength in liquid and large-cap categories.\n'
        '5. Investor age distribution is skewed toward the 30-45 cohort, which also shows higher SIP amounts.\n'
        '6. The gender split highlights potential growth opportunities among female investors.\n'
        '7. City tier distribution underscores strong participation from T30 metros.\n'
        '8. Folio counts nearly doubled from 13.26 Cr to 26.12 Cr between Jan 2022 and Dec 2025.\n'
        '9. Daily NAV return correlations show funds clustering by behavior, indicating sector/style relationships.\n'
        '10. Sector allocation is concentrated in a few high-weight sectors, reinforcing concentration risk and thematic exposure.\n'
    )
]
nb.metadata = {
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python', 'version': '3.x'}
}
with open('EDA_Analysis.ipynb', 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)
