# import pandas as pd
# from openpyxl import load_workbook

# # Paths
# input_file = "/Users/moritzschillinger/Downloads/000_unmixing/ErsteAuswertung_ithera.xlsx"
# output_file = (
#     "/Users/moritzschillinger/Downloads/000_unmixing/results_combined.xlsx"
# )

# # Load workbook with openpyxl (for cell inspection)
# wb = load_workbook(input_file, data_only=True)

# # Also load with pandas
# xlsx = pd.ExcelFile(input_file, engine="openpyxl")

# rows = []

# for sheet in xlsx.sheet_names:

#     if sheet == "TEMPLATE":
#         continue

#     if " (!)" in sheet:
#         sheet_name = sheet.split(" ")[0]
#     elif "(!)" in sheet:
#         sheet_name = sheet.split("(")[0]
#     else:
#         sheet_name = sheet

#     print(f"Processing sheet: {sheet}")

#     ws = wb[sheet]

#     scan_header_row = None

#     # Find the row where column H contains "Scan #"
#     for row in range(1, ws.max_row + 1):
#         if ws[f"H{row}"].value == "Scan #":
#             scan_header_row = row
#             break

#     if scan_header_row is None:
#         print(f"⚠️  'Scan #' not found in sheet {sheet}, skipping.")
#         continue

#     # Read the 5 rows *below* "Scan #"
#     df = pd.read_excel(
#         input_file,
#         sheet_name=sheet,
#         usecols="H",
#         skiprows=scan_header_row,
#         nrows=5,
#         header=None,
#         engine="openpyxl",
#     )

#     values = df.iloc[:, 0].tolist()

#     # Ensure exactly 5 columns
#     values += [None] * (5 - len(values))
#     values = values[:5]

#     row = [sheet_name] + values
#     rows.append(row)


# # Sort rows by sheet number (numeric, ascending)
# rows.sort(key=lambda r: float(r[0]))

# # Create combined DataFrame

# columns = [
#     "Study",
#     "BASELINE",
#     "OCCLUSION",
#     "RELEASE",
#     "POST-OCCLUSION",
#     "PROVOCATION",
# ]
# combined_df = pd.DataFrame(rows, columns=columns)

# # Write output
# with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
#     combined_df.to_excel(writer, sheet_name="Combined", index=False)

# print("✅ Combined sheet created successfully.")


import pandas as pd
import re

# Path to your combined table
file_path = "/Users/moritzschillinger/Downloads/000_unmixing/FST_Lookup.xlsx"


output_overlap_report = (
    "/Users/moritzschillinger/Downloads/000_unmixing/FST_Lookup_report.xlsx"
)
output_fixed_table = (
    "/Users/moritzschillinger/Downloads/000_unmixing/FST_Lookup_fixed.xlsx"
)

# Columns containing scan ranges
phase_cols = [
    "Baseline",
    "Occlusion",
    "Release",
    "Post-Occlusion",
    "Provocation",
]
phase_priority = [
    "Post-Occlusion",
    "Baseline",
    "Provocation",
    "Occlusion",
    "Release",
]
# phase_priority = [
#     "Post-Occlusion",
#     "Baseline",
#     "Provocation",
#     "Release",
#     "Occlusion",
# ]

# Read the table
df = pd.read_excel(file_path, sheet_name="Phase")


def parse_scans(scan_str):
    """Convert 'Scan 10 - 12' into a set of integers {10, 11, 12}."""
    if pd.isna(scan_str) or not isinstance(scan_str, str):
        return set()
    match = re.findall(r"\d+", scan_str)
    if len(match) == 2:
        start, end = map(int, match)
        return set(range(start, end + 1))
    elif len(match) == 1:
        return {int(match[0])}
    else:
        return set()


def scans_to_str(scan_set):
    """Convert a set of integers to a scan range string."""
    if not scan_set:
        return ""
    sorted_scans = sorted(scan_set)
    ranges = []
    start = prev = sorted_scans[0]
    for n in sorted_scans[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append(
                f"Scan {start} - {prev}" if start != prev else f"Scan {start}"
            )
            start = prev = n
    ranges.append(
        f"Scan {start} - {prev}" if start != prev else f"Scan {start}"
    )
    return ", ".join(ranges)


# Store overlaps
overlap_results = []

# New fixed table
fixed_rows = []

for idx, row in df.iterrows():
    study_id = row["Study ID"]

    # Parse scans for each phase
    phase_scans = {phase: parse_scans(row[phase]) for phase in phase_cols}

    # Detect overlaps
    overlaps = []
    for i in range(len(phase_cols)):
        for j in range(i + 1, len(phase_cols)):
            p1, p2 = phase_cols[i], phase_cols[j]
            common = phase_scans[p1] & phase_scans[p2]
            if common:
                overlaps.append(f"{p1} & {p2}: {sorted(common)}")

    if overlaps:
        overlap_results.append(
            {"Study ID": study_id, "Overlaps": "; ".join(overlaps)}
        )

    # Fix overlaps based on priority
    all_scans = {}
    for phase in phase_priority:
        # Remove any scans already assigned to higher-priority phases
        phase_scans[phase] -= set().union(*all_scans.values())
        all_scans[phase] = phase_scans[phase]

    # Convert back to scan strings
    fixed_row = {"Study ID": study_id}
    for phase in phase_cols:
        fixed_row[phase] = scans_to_str(all_scans[phase])

    fixed_rows.append(fixed_row)

# Convert overlaps to DataFrame
overlap_df = pd.DataFrame(overlap_results)

# Convert fixed table to DataFrame
fixed_df = pd.DataFrame(fixed_rows)

# Save results
overlap_df.to_excel(output_overlap_report, index=False)
fixed_df.to_excel(output_fixed_table, index=False)

print("✅ Overlap report and fixed table created successfully.")
