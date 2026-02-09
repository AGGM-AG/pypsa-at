import marimo

__generated_with = "0.17.6"
app = marimo.App(width="medium")


@app.cell
def _():
    # inspect scigrid-gas data
    # ../data/gas_network/scigrid-gas/data
    data_folder = "/IdeaProjects/pypsa-at/data/gas_network/scigrid-gas/data/"
    import pandas as pd

    # for file in os.listdir(data_folder):
    #     if file.endswith('.csv'):
    #         print(file)

    file_segments = pd.read_csv(data_folder + "IGGIELGN_PipeSegments.csv", sep=";")
    file_segments_AT = file_segments[
        file_segments["country_code"].str.contains("AT", na=False)
    ]
    # file_segments_AT
    return data_folder, file_segments_AT, pd


@app.cell
def _(file_segments_AT):
    file_segments_AT.loc[351]
    return


@app.cell
def _(data_folder, pd):
    file_productions = pd.read_csv(data_folder + "IGGIELGN_Productions.csv", sep=";")
    # since there's no production in Austria, use Germany instead:
    file_productions_DE = file_productions[
        file_productions["country_code"].str.contains("DE", na=False)
    ]
    file_productions_DE.loc[100]
    return


if __name__ == "__main__":
    app.run()
