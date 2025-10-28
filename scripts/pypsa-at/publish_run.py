"""Send run results to database for display in dashboard."""


# archive content:
# runs.json
#

# run.json
# {
#   "model": "TestModel",
#   "version": "1.0.0",
#   "scenario": "upload_test",
#   "description": "Test scenario for upload endpoint integration test",
#   "author": "Test Suite",
#   "custom_metadata": {
#     "test_run": true,
#     "timestamp": "2025-01-23T12:00:00Z"
#   }
# }

# variables.csv
# region,variable,unit,time,value
# TEST,Primary Energy|Test,GWh,2050-01-01,100.0
# TEST,Primary Energy|Test,GWh,2050-02-01,150.0
# TEST,Primary Energy|Test,GWh,2050-03-01,200.0
# TEST,Secondary Energy|Test,GWh,2050-01-01,50.0
# TEST,Secondary Energy|Test,GWh,2050-02-01,75.0

# plot.json
# {
#   "plot_type": "test_plot",
#   "location": "TEST",
#   "bus_carrier": "test_carrier",
#   "specifier": "test",
#   "year": 2050,
#   "plotly_dict": {
#     "data": [
#       {
#         "x": [1, 2, 3],
#         "y": [10, 20, 30],
#         "type": "scatter",
#         "name": "Test Data"
#       }
#     ],
#     "layout": {
#       "title": "Test Plot for Upload",
#       "xaxis": {"title": "X Axis"},
#       "yaxis": {"title": "Y Axis"}
#     }
#   }
# }
