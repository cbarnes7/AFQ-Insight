"""Generate samples of synthetic data sets or extract AFQ data."""
import numpy as np
import os.path as op
import pandas as pd

from collections import namedtuple
from shutil import copyfile
from sklearn.preprocessing import LabelEncoder

from .transform import AFQDataFrameMapper

__all__ = ["load_afq_data", "output_beta_to_afq"]


def load_afq_data(
    workdir,
    dwi_metrics=None,
    target_cols=None,
    label_encode_cols=None,
    index_col="subjectID",
    fn_nodes="nodes.csv",
    fn_subjects="subjects.csv",
    unsupervised=False,
    concat_subject_session=False,
    return_sessions=False,
):
    """Load AFQ data from CSV, transform it, return feature matrix and target.

    This function expects a directory with a diffusion metric csv file
    (specified by ``fn_nodes``) and, optionally, a phenotypic data file
    (specified by ``fn_subjects``). The nodes csv file must be a long format
    dataframe with the following columns: "subjectID," "nodeID," "tractID,"
    an optional "sessionID". All other columns are assumed to be diffusion
    metric columns, which can be optionally subset using the ``dwi_metrics``
    parameter.

    For supervised learning problems (with parameter ``unsupervised=False``)
    this function will also load phenotypic targets from a subjects csv/tsv
    file. This function will load the subject data, drop subjects that are
    not found in the dwi feature matrix, and optionally label encode
    categorical values.

    Parameters
    ----------
    workdir : str
        Directory in which to find the AFQ csv files

    dwi_metrics : list of strings, optional
        List of diffusion metrics to extract from nodes csv.
        e.g. ["dki_md", "dki_fa"]

    target_cols : list of strings, optional
        List of column names in subjects csv file to use as target variables

    label_encode_cols : list of strings, subset of target_cols
        Must be a subset of target_cols. These columns will be encoded using
        :class:`sklearn:sklearn.preprocessing.LabelEncoder`.

    index_col : str, default='subjectID'
        The name of column in the subject csv file to use as the index. This
        should contain subject IDs.

    fn_nodes : str, default='nodes.csv'
        Filename for the nodes csv file.

    fn_subjects : str, default='subjects.csv'
        Filename for the subjects csv file.

    unsupervised : bool, default=False
        If True, do not load target data from the ``fn_subjects`` file.

    concat_subject_session : bool, default=False
        If True, create new subject IDs by concatenating the existing subject
        IDs with the session IDs. This is useful when subjects have multiple
        sessions and you with to disambiguate between them.

    return_sessions : bool, default=False
        If True, return sessionID

    Returns
    -------
    X : array-like of shape (n_samples, n_features)
        The feature samples.

    y : array-like of shape (n_samples,) or (n_samples, n_targets), optional
        Target values. Returned only if ``unsupervised`` is False

    groups : list of numpy.ndarray
        feature indices for each feature group

    feature_names : list of tuples
        The multi-indexed columns of X

    group_names : list of tuples
        The multi-indexed groups of X

    subjects : list
        Subject IDs

    sessions : list
        Session IDs. Returned only if ``return_sessions`` is True.

    classes : dict
        Class labels for each column specified in ``label_encode_cols``.
        Returned only if ``unsupervised`` is False

    See Also
    --------
    transform.AFQDataFrameMapper
    """
    workdir = op.abspath(workdir)
    fn_nodes = op.join(workdir, fn_nodes)
    fn_subjects = op.join(workdir, fn_subjects)

    nodes = pd.read_csv(fn_nodes)
    unnamed_cols = [col for col in nodes.columns if "Unnamed:" in col]
    nodes.drop(unnamed_cols, axis="columns", inplace=True)

    sessions = nodes["sessionID"] if "sessionID" in nodes.columns else None
    if concat_subject_session:
        nodes["subjectID"] = nodes["subjectID"] + nodes["sessionID"].astype(str)

    nodes.drop("sessionID", axis="columns", inplace=True, errors="ignore")

    if dwi_metrics is not None:
        nodes = nodes[["tractID", "nodeID", "subjectID"] + dwi_metrics]

    mapper = AFQDataFrameMapper()
    X = mapper.fit_transform(nodes)
    groups = mapper.groups_
    feature_names = mapper.feature_names_
    group_names = [tup[0:2] for tup in feature_names if tup[2] == 0]
    subjects = mapper.subjects_

    if unsupervised:
        if return_sessions:
            output = X, groups, feature_names, group_names, subjects, sessions
        else:
            output = X, groups, feature_names, group_names, subjects
    else:
        # Read using sep=None, engine="python" to allow for both csv and tsv
        targets = pd.read_csv(
            fn_subjects, sep=None, engine="python", index_col=index_col
        )

        # Drop unnamed columns
        unnamed_cols = [col for col in targets.columns if "Unnamed:" in col]
        targets.drop(unnamed_cols, axis="columns", inplace=True)

        # Drop subjects that are not in the dwi feature matrix
        targets = pd.DataFrame(index=subjects).merge(
            targets, how="left", left_index=True, right_index=True
        )

        # Select user defined target columns
        if target_cols is not None:
            y = targets.loc[:, target_cols]

        # Label encode the user-supplied categorical columns
        classes = {}
        if label_encode_cols is not None:
            if not set(label_encode_cols) <= set(target_cols):
                raise ValueError(
                    "label_encode_cols must be a subset of target_cols; "
                    "got {0} instead.".format(label_encode_cols)
                )

            le = LabelEncoder()
            for col in label_encode_cols:
                y.loc[:, col] = le.fit_transform(y[col])
                classes[col] = le.classes_

        y = np.squeeze(y.to_numpy())

        if return_sessions:
            output = (
                X,
                y,
                groups,
                feature_names,
                group_names,
                subjects,
                sessions,
                classes,
            )
        else:
            output = X, y, groups, feature_names, group_names, subjects, classes

    return output


def output_beta_to_afq(
    beta_hat,
    columns,
    workdir_in,
    workdir_out,
    fn_nodes_in="nodes.csv",
    fn_subjects_in="subjects.csv",
    fn_nodes_out="nodes.csv",
    fn_subjects_out="subjects.csv",
    scale_beta=False,
):
    """Output coefficients to AFQ data format.

    Parameters
    ----------
    workdir_in : str
        Directory in which to find the input AFQ csv files

    workdir_out : str
        Directory in which to save the output AFQ csv files

    fn_nodes_in : str, default='nodes.csv'
        Filename for the input nodes csv file.

    fn_subjects_in : str, default='subjects.csv'
        Filename for the input subjects csv file.

    fn_nodes_out : str, default='nodes.csv'
        Filename for the output nodes csv file.

    fn_subjects_out : str, default='subjects.csv'
        Filename for the output subjects csv file.

    scale_beta : bool, default=False
        If True, scale the beta coefficients to have the same mean and
        variance as other values for the same metric and tract.

    Returns
    -------
    collections.namedtuple
        namedtuple with fields:
        nodes_file - output nodes csv file path
        subjects_file - output subjects csv file path
    """
    workdir_in = op.abspath(workdir_in)
    fn_nodes_in = op.join(workdir_in, fn_nodes_in)
    fn_subjects_in = op.join(workdir_in, fn_subjects_in)

    workdir_out = op.abspath(workdir_out)
    fn_nodes_out = op.join(workdir_out, fn_nodes_out)
    fn_subjects_out = op.join(workdir_out, fn_subjects_out)

    if op.samefile(workdir_in, workdir_out):
        raise ValueError(
            "output directory equals input directory, please "
            "output to a different directory to avoid "
            "overwriting your files."
        )

    df_nodes = pd.read_csv(fn_nodes_in)

    df_beta = pd.DataFrame(columns=columns)
    df_beta.loc["value"] = beta_hat
    df_beta = df_beta.transpose()
    df_beta = df_beta.unstack(level="metric")
    df_beta.columns = [t[-1] for t in df_beta.columns]
    df_beta.reset_index(inplace=True)
    df_beta["subjectID"] = "beta_hat"
    df_beta = df_beta[df_nodes.columns]

    if scale_beta:
        # For each tract-metric scale the beta_hat values to have the
        # same mean and standard deviation as the subjects' tract-metric
        # values. Suppose we have beta values given by x_i with mean `b_mean`
        # and standard deviation `b_std` and we want to arrive at a similar
        # set with mean `f_mean` and standard deviation `f_std`:
        #     y_i = f_mean + (x_i - b_mean) * f_std / b_std
        for tract in df_nodes["tractID"].unique():
            f_mean = (
                df_nodes.drop(["tractID", "subjectID", "nodeID"], axis="columns")
                .loc[df_nodes["tractID"] == tract]
                .mean()
            )

            f_std = (
                df_nodes.drop(["tractID", "subjectID", "nodeID"], axis="columns")
                .loc[df_nodes["tractID"] == tract]
                .std()
            )

            b_mean = (
                df_beta.drop(["tractID", "subjectID", "nodeID"], axis="columns")
                .loc[df_beta["tractID"] == tract]
                .mean()
            )

            b_std = (
                df_beta.drop(["tractID", "subjectID", "nodeID"], axis="columns")
                .loc[df_beta["tractID"] == tract]
                .std()
            )

            metrics = b_mean.index
            df_beta.loc[df_beta["tractID"] == tract, metrics] = f_mean + (
                df_beta.loc[df_beta["tractID"] == tract, metrics] - b_mean
            ) * f_std.divide(b_std).replace([np.inf, -np.inf], 1)

    df_nodes = pd.concat([df_nodes, df_beta], axis="rows", ignore_index=True)
    df_nodes.to_csv(fn_nodes_out, index=False)

    df_subjects = pd.read_csv(fn_subjects_in, index_col=0)
    subject_row = {key: "" for key in df_subjects.columns}
    subject_row["subjectID"] = "beta_hat"
    df_subjects.loc[len(df_subjects)] = subject_row
    df_subjects.to_csv(fn_subjects_out, index=True)

    fn_streamlines_in = op.join(workdir_in, "streamlines.json")
    fn_streamlines_out = op.join(workdir_out, "streamlines.json")
    copyfile(fn_streamlines_in, fn_streamlines_out)

    fn_params_in = op.join(workdir_in, "params.json")
    fn_params_out = op.join(workdir_out, "params.json")
    copyfile(fn_params_in, fn_params_out)

    OutputFiles = namedtuple("OutputFiles", "nodes_file subjects_file")

    return OutputFiles(nodes_file=fn_nodes_out, subjects_file=fn_subjects_out)
