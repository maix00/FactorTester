import re

with open('server/modules/single_factor_test/ic.py', 'r') as f:
    text = f.read()

header = text[:text.find("        cache_dir_ic     = Path('../data/cache/ic')")]

footer = text[text.find("        # 从 tester.factor_ic_stats 汇总"):]
# uncomment the footer
footer_lines = footer.split('\n')
uncommented_footer = []
for line in footer_lines:
    if line.startswith('        #     ') or line.startswith('        # ') or line.startswith('        #'):
        uncommented_footer.append(line.replace('        # ', '        ', 1).replace('        #', '        ', 1))
    else:
        uncommented_footer.append(line)
footer = '\n'.join(uncommented_footer)

# Also fix the `factor.table.columns` to `f._ic_fe_intermediate.columns`!
footer = footer.replace(
    'factor.table.columns if factor.table is not None else []',
    "factor._ic_fe_intermediate.columns if getattr(factor, '_ic_fe_intermediate', None) is not None else []"
)

middle = """
        all_products = tester.products.copy()

        try:
            returns_col = FactorNextPeriodReturns.NEXT_OPEN_TO_OPEN_ADJUSTED
            return_freqs_ic = {f: return_freqs.get(f, None) for f in factors}
            common_rf = next((rf for rf in return_freqs_ic.values() if rf is not None), None)

            tester.products = all_products.copy()
            ic_s_df, ic_st_df = tester.calc_ic(
                factors=factors, return_freq=common_rf,
                returns_col=returns_col, parallel=True)
            
        except Exception as e:
            return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
        finally:
            tester.products = all_products.copy()

"""

new_text = header + middle + footer

# Fix paths_hash
new_text = new_text.replace("'paths_hash': paths_hash,", "")

with open('server/modules/single_factor_test/ic.py', 'w') as f:
    f.write(new_text)

