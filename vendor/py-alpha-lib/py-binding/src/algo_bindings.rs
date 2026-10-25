  /// Calculate absolute value of input elements
  #[pyfunction]
  fn abs<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_abs(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_abs(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_abs(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_abs(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Check if condition is always true within moving window of `periods` (or cumulative if `periods` is 0)
  #[pyfunction]
  fn all<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, bool>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_all(&ctx, r, condition, periods).map_err(|e| e.into())
    } else if let Some((r, condition)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()) {
      ctx._groups = 1;
      if r.len() != condition.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, bool>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_all(&ctx, r, condition, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else { Err(PyValueError::new_err("invalid input list (expected bool, bool)")) }
    } else { Err(PyValueError::new_err("invalid input (expected bool, bool)")) }
  }
  /// Rolling Jensen's Alpha of asset returns against benchmark returns.
  #[pyfunction]
  fn alpha<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    benchmark: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), benchmark)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(benchmark.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let benchmark = benchmark.as_array();
      let benchmark = benchmark.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_alpha(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), benchmark)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(benchmark.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let benchmark = benchmark.as_array();
      let benchmark = benchmark.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_alpha(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
    } else if let Some(((r, input), benchmark)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(benchmark.cast::<PyList>().ok()) {
      if r.len() != input.len() || benchmark.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), benchmark)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(benchmark.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let benchmark = benchmark.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(benchmark.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let benchmark = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_alpha(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), benchmark)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(benchmark.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let benchmark = benchmark.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(benchmark.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let benchmark = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_alpha(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Check if condition is true at least once within moving window of `periods` (or cumulative if `periods` is 0)
  #[pyfunction]
  fn any<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, bool>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_any(&ctx, r, condition, periods).map_err(|e| e.into())
    } else if let Some((r, condition)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()) {
      ctx._groups = 1;
      if r.len() != condition.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, bool>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_any(&ctx, r, condition, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else { Err(PyValueError::new_err("invalid input list (expected bool, bool)")) }
    } else { Err(PyValueError::new_err("invalid input (expected bool, bool)")) }
  }
  /// Rolling argmax of the trailing window.
  #[pyfunction]
  fn argmax<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_argmax(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_argmax(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmax(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmax(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling argmax expressed as a window offset in `0..periods-1`.
  #[pyfunction]
  fn argmax_raw<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_argmax_raw(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_argmax_raw(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmax_raw(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmax_raw(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling argmin of the trailing window; same contract as `ta_argmax`.
  #[pyfunction]
  fn argmin<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_argmin(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_argmin(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmin(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmin(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling argmin expressed as a window offset in `0..periods-1`.
  #[pyfunction]
  fn argmin_raw<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_argmin_raw(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_argmin_raw(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmin_raw(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_argmin_raw(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Forward-fill NaN values with the last valid observation
  #[pyfunction]
  fn backfill<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_backfill(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_backfill(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_backfill(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_backfill(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// If condition is true, set current position and previous `periods - 1` periods (total `periods` bars) to true
  #[pyfunction]
  fn backset<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, bool>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_backset(&ctx, r, condition, periods).map_err(|e| e.into())
    } else if let Some((r, condition)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()) {
      ctx._groups = 1;
      if r.len() != condition.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, bool>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_backset(&ctx, r, condition, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else { Err(PyValueError::new_err("invalid input list (expected bool, bool)")) }
    } else { Err(PyValueError::new_err("invalid input (expected bool, bool)")) }
  }
  /// Calculate number of bars since last condition true
  #[pyfunction]
  fn barslast<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_barslast(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_barslast(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array output and bool input
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_barslast(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array output
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_barslast(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate number of bars since first condition true
  #[pyfunction]
  fn barssince<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_barssince(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_barssince(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array output and bool input
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_barssince(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array output
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_barssince(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling Beta coefficient of asset returns against benchmark returns.
  #[pyfunction]
  fn beta<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    benchmark: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), benchmark)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(benchmark.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let benchmark = benchmark.as_array();
      let benchmark = benchmark.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_beta(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), benchmark)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(benchmark.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let benchmark = benchmark.as_array();
      let benchmark = benchmark.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_beta(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
    } else if let Some(((r, input), benchmark)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(benchmark.cast::<PyList>().ok()) {
      if r.len() != input.len() || benchmark.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), benchmark)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(benchmark.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let benchmark = benchmark.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(benchmark.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let benchmark = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_beta(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), benchmark)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(benchmark.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let benchmark = benchmark.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(benchmark.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let benchmark = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_beta(&ctx, r, input, benchmark, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Discretize the input into n bins, the ctx.groups() is the number of groups
  #[pyfunction]
  fn bins<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    bins: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_bins(&ctx, r, input, bins).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_bins(&ctx, r, input, bins).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_bins(&ctx, r, input, bins).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_bins(&ctx, r, input, bins).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Backward split and dividend adjustment
  #[pyfunction]
  fn bw_split<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    price: &'py Bound<'_, PyAny>,
    dividend: &'py Bound<'_, PyAny>,
    transfer_shares: &'py Bound<'_, PyAny>,
    right_shares: &'py Bound<'_, PyAny>,
    right_price: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_bw_split(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_bw_split(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Backward split factor calculation
  #[pyfunction]
  fn bw_split_factor<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    price: &'py Bound<'_, PyAny>,
    dividend: &'py Bound<'_, PyAny>,
    transfer_shares: &'py Bound<'_, PyAny>,
    right_shares: &'py Bound<'_, PyAny>,
    right_price: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_bw_split_factor(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_bw_split_factor(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate rank percentage cross group dimension, the ctx.groups() is the number of groups
  #[pyfunction]
  fn cc_rank<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cc_rank(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_cc_rank(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_cc_rank(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_cc_rank(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate cross-sectional Z-Score across groups at each time step
  #[pyfunction]
  fn cc_zscore<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cc_zscore(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_cc_zscore(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_cc_zscore(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_cc_zscore(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Time Series Correlation in moving window on self
  #[pyfunction]
  fn corr<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_corr(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_corr(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_corr(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_corr(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate two series correlation over a moving window
  #[pyfunction]
  fn corr2<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    x: &'py Bound<'_, PyAny>,
    y: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, x), y)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(x.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(y.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_corr2(&ctx, r, x, y, periods).map_err(|e| e.into())
    } else if let Some(((mut r, x), y)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(x.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(y.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_corr2(&ctx, r, x, y, periods).map_err(|e| e.into())
    } else if let Some(((r, x), y)) = r.cast::<PyList>().ok().zip(x.cast::<PyList>().ok()).zip(y.cast::<PyList>().ok()) {
      if r.len() != x.len() || y.len() != x.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, x), y)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(x.into_par_iter()).zip(y.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let x = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let y = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_corr2(&ctx, r, x, y, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, x), y)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(x.into_par_iter()).zip(y.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let x = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let y = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_corr2(&ctx, r, x, y, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Rolling correlation on pairwise-valid observations.
  #[pyfunction]
  fn corr_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    left: &'py Bound<'_, PyAny>,
    right: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_corr_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
    } else if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_corr_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
    } else if let Some(((r, left), right)) = r.cast::<PyList>().ok().zip(left.cast::<PyList>().ok()).zip(right.cast::<PyList>().ok()) {
      if r.len() != left.len() || right.len() != left.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_corr_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_corr_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate number of periods where condition is true in passed `periods` window
  #[pyfunction]
  fn count<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_count(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_count(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array output and bool input
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_count(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array output
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_count(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Count number of NaN values in a rolling window
  #[pyfunction]
  fn count_nans<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_count_nans(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_count_nans(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_count_nans(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_count_nans(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate number of periods where condition is true in passed variable `periods` window
  #[pyfunction]
  fn count_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_count_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, bool>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_count_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_count_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_count_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, bool, int)")) }
  }
  /// Calculate Covariance over a moving window
  #[pyfunction]
  fn cov<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    x: &'py Bound<'_, PyAny>,
    y: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, x), y)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(x.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(y.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cov(&ctx, r, x, y, periods).map_err(|e| e.into())
    } else if let Some(((mut r, x), y)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(x.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(y.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cov(&ctx, r, x, y, periods).map_err(|e| e.into())
    } else if let Some(((r, x), y)) = r.cast::<PyList>().ok().zip(x.cast::<PyList>().ok()).zip(y.cast::<PyList>().ok()) {
      if r.len() != x.len() || y.len() != x.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, x), y)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(x.into_par_iter()).zip(y.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let x = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let y = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_cov(&ctx, r, x, y, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, x), y)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(x.into_par_iter()).zip(y.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let x = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let y = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_cov(&ctx, r, x, y, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Rolling covariance on pairwise-valid observations (ddof=1).
  #[pyfunction]
  fn cov_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    left: &'py Bound<'_, PyAny>,
    right: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cov_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
    } else if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cov_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
    } else if let Some(((r, left), right)) = r.cast::<PyList>().ok().zip(left.cast::<PyList>().ok()).zip(right.cast::<PyList>().ok()) {
      if r.len() != left.len() || right.len() != left.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_cov_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_cov_nan(&ctx, r, left, right, periods, min_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// For 2 arrays A and B, return true if A[i-1] < B[i-1] and A[i] >= B[i]
  #[pyfunction]
  fn cross<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, bool>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_cross(&ctx, r, a, b).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected bool, float, float)")) }
  }
  /// Exponential Moving Average
  #[pyfunction]
  fn dma<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    weight: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_dma(&ctx, r, input, weight).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_dma(&ctx, r, input, weight as f32).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_dma(&ctx, r, input, weight).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_dma(&ctx, r, input, weight as f32).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Exponential Moving Average with variable weight
  #[pyfunction]
  fn dma_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    weight: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), weight)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(weight.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weight = weight.as_array();
      let weight = weight.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_dma_v(&ctx, r, input, weight).map_err(|e| e.into())
    } else if let Some(((mut r, input), weight)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(weight.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weight = weight.as_array();
      let weight = weight.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_dma_v(&ctx, r, input, weight).map_err(|e| e.into())
    } else if let Some(((r, input), weight)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(weight.cast::<PyList>().ok()) {
      if r.len() != input.len() || weight.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), weight)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(weight.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let weight = weight.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(weight.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let weight = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_dma_v(&ctx, r, input, weight).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), weight)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(weight.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let weight = weight.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(weight.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let weight = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_dma_v(&ctx, r, input, weight).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Exponential moving average matching pandas `ewm(span=periods, adjust=True, ignore_na=False).mean()`.
  #[pyfunction]
  fn ema_adjust<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ema_adjust(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ema_adjust(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ema_adjust(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ema_adjust(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Exponential Moving Average with variable periods
  #[pyfunction]
  fn ema_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ema_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ema_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ema_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ema_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Calculate rolling Shannon entropy over a moving window
  #[pyfunction]
  fn entropy<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    bins: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_entropy(&ctx, r, input, periods, bins).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_entropy(&ctx, r, input, periods, bins).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_entropy(&ctx, r, input, periods, bins).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_entropy(&ctx, r, input, periods, bins).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Filter consecutive signals: once condition is true, set subsequent `periods` periods to false
  #[pyfunction]
  fn filter<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, bool>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_filter(&ctx, r, condition, periods).map_err(|e| e.into())
    } else if let Some((r, condition)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()) {
      ctx._groups = 1;
      if r.len() != condition.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, bool>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_filter(&ctx, r, condition, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else { Err(PyValueError::new_err("invalid input list (expected bool, bool)")) }
    } else { Err(PyValueError::new_err("invalid input (expected bool, bool)")) }
  }
  /// Future Return
  #[pyfunction]
  fn fret<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    open: &'py Bound<'_, PyAny>,
    close: &'py Bound<'_, PyAny>,
    is_calc: &'py Bound<'_, PyAny>,
    delay: usize,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, open), close), is_calc)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(open.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(close.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(is_calc.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let open = open.as_array();
      let open = open.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let close = close.as_array();
      let close = close.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let is_calc = is_calc.as_array();
      let is_calc = is_calc.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fret(&ctx, r, open, close, is_calc, delay, periods).map_err(|e| e.into())
    } else if let Some((((mut r, open), close), is_calc)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(open.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(close.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(is_calc.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let open = open.as_array();
      let open = open.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let close = close.as_array();
      let close = close.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let is_calc = is_calc.as_array();
      let is_calc = is_calc.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fret(&ctx, r, open, close, is_calc, delay, periods).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Sequential average-cost fill chain.
  #[pyfunction]
  fn ft_average_cost_chain<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    fill_qty: &'py Bound<'_, PyAny>,
    price: &'py Bound<'_, PyAny>,
    multiplier: &'py Bound<'_, PyAny>,
    prior_qty: f64,
    prior_cost: f64,
    mode: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, fill_qty), price), multiplier)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(fill_qty.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(price.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(multiplier.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let fill_qty = fill_qty.as_array();
      let fill_qty = fill_qty.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let multiplier = multiplier.as_array();
      let multiplier = multiplier.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_average_cost_chain(&ctx, r, fill_qty, price, multiplier, prior_qty, prior_cost, mode).map_err(|e| e.into())
    } else if let Some((((mut r, fill_qty), price), multiplier)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(fill_qty.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(price.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(multiplier.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let fill_qty = fill_qty.as_array();
      let fill_qty = fill_qty.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let multiplier = multiplier.as_array();
      let multiplier = multiplier.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_average_cost_chain(&ctx, r, fill_qty, price, multiplier, prior_qty as f32, prior_cost as f32, mode).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Bar visibility timestamps relative to the first bar.
  #[pyfunction]
  fn ft_bar_visibility<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    indices: &'py Bound<'_, PyAny>,
    open_basis: usize,
    open_delay: f64,
    end_delay: f64,
    freq: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, indices)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let indices = indices.as_array();
      let indices = indices
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_bar_visibility(&ctx, r, indices, open_basis, open_delay, end_delay, freq).map_err(|e| e.into())
    } else if let Some((mut r, indices)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let indices = indices.as_array();
      let indices = indices
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ft_bar_visibility(&ctx, r, indices, open_basis, open_delay as f32, end_delay as f32, freq as f32).map_err(|e| e.into())
    } else if let Some((r, indices)) = r.cast::<PyList>().ok().zip(indices.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != indices.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, indices)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(indices.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let indices = input.as_slice();
            if let Some((r, indices)) = r.zip(indices) {
              ta_ft_bar_visibility(&ctx, r, indices, open_basis, open_delay, end_delay, freq).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, indices)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(indices.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let indices = input.as_slice();
            if let Some((r, indices)) = r.zip(indices) {
              ta_ft_bar_visibility(&ctx, r, indices, open_basis, open_delay as f32, end_delay as f32, freq as f32).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Cross-sectional Pearson correlation per timestamp.
  #[pyfunction]
  fn ft_corr<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    left: &'py Bound<'_, PyAny>,
    right: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_corr(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_corr(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((r, left), right)) = r.cast::<PyList>().ok().zip(left.cast::<PyList>().ok()).zip(right.cast::<PyList>().ok()) {
      if r.len() != left.len() || right.len() != left.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_corr(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_corr(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Cross-sectional covariance per timestamp (ddof=1).
  #[pyfunction]
  fn ft_cov<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    left: &'py Bound<'_, PyAny>,
    right: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_cov(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_cov(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((r, left), right)) = r.cast::<PyList>().ok().zip(left.cast::<PyList>().ok()).zip(right.cast::<PyList>().ok()) {
      if r.len() != left.len() || right.len() != left.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_cov(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_cov(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Polynomial fit over the first `depth` valid (days, value) pairs:
  #[pyfunction]
  fn ft_curve_fit<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    values: &'py Bound<'_, PyAny>,
    days: &'py Bound<'_, PyAny>,
    lengths: &'py Bound<'_, PyAny>,
    depth: usize,
    op: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, values), days), lengths)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(values.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(days.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(lengths.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let values = values.as_array();
      let values = values.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let days = days.as_array();
      let days = days.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lengths = lengths.as_array();
      let lengths = lengths.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_curve_fit(&ctx, r, values, days, lengths, depth, op).map_err(|e| e.into())
    } else if let Some((((mut r, values), days), lengths)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(values.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(days.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(lengths.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let values = values.as_array();
      let values = values.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let days = days.as_array();
      let days = days.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lengths = lengths.as_array();
      let lengths = lengths.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_curve_fit(&ctx, r, values, days, lengths, depth, op).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Pairwise curve op: 0 spread, 1 ratio, 2 log-ratio, 3 contango,
  #[pyfunction]
  fn ft_curve_pair<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    values: &'py Bound<'_, PyAny>,
    days: &'py Bound<'_, PyAny>,
    lengths: &'py Bound<'_, PyAny>,
    near: usize,
    far: usize,
    op: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, values), days), lengths)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(values.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(days.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(lengths.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let values = values.as_array();
      let values = values.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let days = days.as_array();
      let days = days.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lengths = lengths.as_array();
      let lengths = lengths.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_curve_pair(&ctx, r, values, days, lengths, near, far, op).map_err(|e| e.into())
    } else if let Some((((mut r, values), days), lengths)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(values.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(days.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(lengths.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let values = values.as_array();
      let values = values.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let days = days.as_array();
      let days = days.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lengths = lengths.as_array();
      let lengths = lengths.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_curve_pair(&ctx, r, values, days, lengths, near, far, op).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Dynamic truncated rolling arg-extreme.
  #[pyfunction]
  fn ft_dynamic_arg<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    starts: &'py Bound<'_, PyAny>,
    ends: &'py Bound<'_, PyAny>,
    period: usize,
    flags: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, input), starts), ends)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(starts.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(ends.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let starts = starts.as_array();
      let starts = starts.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ends = ends.as_array();
      let ends = ends.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_dynamic_arg(&ctx, r, input, starts, ends, period, flags).map_err(|e| e.into())
    } else if let Some((((mut r, input), starts), ends)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(starts.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(ends.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let starts = starts.as_array();
      let starts = starts.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ends = ends.as_array();
      let ends = ends.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_dynamic_arg(&ctx, r, input, starts, ends, period, flags).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Apply the pandas-compatible dynamic truncation mask to a rolling panel.
  #[pyfunction]
  fn ft_dynamic_mask<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    starts: &'py Bound<'_, PyAny>,
    ends: &'py Bound<'_, PyAny>,
    period: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, input), starts), ends)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(starts.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(ends.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let starts = starts.as_array();
      let starts = starts.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ends = ends.as_array();
      let ends = ends.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_dynamic_mask(&ctx, r, input, starts, ends, period).map_err(|e| e.into())
    } else if let Some((((mut r, input), starts), ends)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(starts.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(ends.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let starts = starts.as_array();
      let starts = starts.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ends = ends.as_array();
      let ends = ends.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_dynamic_mask(&ctx, r, input, starts, ends, period).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Stable ordering for backtest events: (timestamp, kind, sequence, push index).
  #[pyfunction]
  fn ft_event_order<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    timestamps: &'py Bound<'_, PyAny>,
    kinds: &'py Bound<'_, PyAny>,
    sequences: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, timestamps), kinds), sequences)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(timestamps.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(kinds.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(sequences.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let timestamps = timestamps.as_array();
      let timestamps = timestamps.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let kinds = kinds.as_array();
      let kinds = kinds.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let sequences = sequences.as_array();
      let sequences = sequences.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_event_order(&ctx, r, timestamps, kinds, sequences).map_err(|e| e.into())
    } else if let Some((((mut r, timestamps), kinds), sequences)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(timestamps.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(kinds.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(sequences.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let timestamps = timestamps.as_array();
      let timestamps = timestamps.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let kinds = kinds.as_array();
      let kinds = kinds.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let sequences = sequences.as_array();
      let sequences = sequences.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_event_order(&ctx, r, timestamps, kinds, sequences).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Batch searchsorted-left over ragged sorted index arrays.
  #[pyfunction]
  fn ft_exec_positions<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    indices: &'py Bound<'_, PyAny>,
    offsets: &'py Bound<'_, PyAny>,
    query: f64,
    _delay: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, indices), offsets)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(offsets.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let indices = indices.as_array();
      let indices = indices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let offsets = offsets.as_array();
      let offsets = offsets.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_exec_positions(&ctx, r, indices, offsets, query, _delay).map_err(|e| e.into())
    } else if let Some(((mut r, indices), offsets)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(offsets.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let indices = indices.as_array();
      let indices = indices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let offsets = offsets.as_array();
      let offsets = offsets.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_exec_positions(&ctx, r, indices, offsets, query as f32, _delay).map_err(|e| e.into())
    } else if let Some(((r, indices), offsets)) = r.cast::<PyList>().ok().zip(indices.cast::<PyList>().ok()).zip(offsets.cast::<PyList>().ok()) {
      if r.len() != indices.len() || offsets.len() != indices.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, indices), offsets)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(offsets.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let offsets = offsets.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(indices.into_par_iter()).zip(offsets.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let indices = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let offsets = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_exec_positions(&ctx, r, indices, offsets, query, _delay).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, indices), offsets)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(offsets.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let offsets = offsets.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(indices.into_par_iter()).zip(offsets.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let indices = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let offsets = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_exec_positions(&ctx, r, indices, offsets, query as f32, _delay).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Batch execution timestamp resolution for ragged sorted index arrays.
  #[pyfunction]
  fn ft_exec_schedule_ts<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    indices: &'py Bound<'_, PyAny>,
    offsets: &'py Bound<'_, PyAny>,
    delay: usize,
    freq: f64,
    open_delay: f64,
    end_delay: f64,
    open_basis: usize,
    mode: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, indices), offsets)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(offsets.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let indices = indices.as_array();
      let indices = indices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let offsets = offsets.as_array();
      let offsets = offsets.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_exec_schedule_ts(&ctx, r, indices, offsets, delay, freq, open_delay, end_delay, open_basis, mode).map_err(|e| e.into())
    } else if let Some(((mut r, indices), offsets)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(indices.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(offsets.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let indices = indices.as_array();
      let indices = indices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let offsets = offsets.as_array();
      let offsets = offsets.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_exec_schedule_ts(&ctx, r, indices, offsets, delay, freq as f32, open_delay as f32, end_delay as f32, open_basis, mode).map_err(|e| e.into())
    } else if let Some(((r, indices), offsets)) = r.cast::<PyList>().ok().zip(indices.cast::<PyList>().ok()).zip(offsets.cast::<PyList>().ok()) {
      if r.len() != indices.len() || offsets.len() != indices.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, indices), offsets)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(offsets.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let offsets = offsets.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(indices.into_par_iter()).zip(offsets.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let indices = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let offsets = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_exec_schedule_ts(&ctx, r, indices, offsets, delay, freq, open_delay, end_delay, open_basis, mode).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, indices), offsets)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(indices.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(offsets.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let indices = indices.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let offsets = offsets.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(indices.into_par_iter()).zip(offsets.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let indices = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let offsets = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_exec_schedule_ts(&ctx, r, indices, offsets, delay, freq as f32, open_delay as f32, end_delay as f32, open_basis, mode).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Category-partitioned cross-sectional transform: 0 = rank, 1 = z-score,
  #[pyfunction]
  fn ft_group<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    mask: &'py Bound<'_, PyAny>,
    category: &'py Bound<'_, PyAny>,
    op: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, input), mask), category)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(category.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_group(&ctx, r, input, mask, category, op).map_err(|e| e.into())
    } else if let Some((((mut r, input), mask), category)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(category.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_group(&ctx, r, input, mask, category, op).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Reduce an ``(entities, rows)`` panel by category.
  #[pyfunction]
  fn ft_group_reduce<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    category: &'py Bound<'_, PyAny>,
    weight: &'py Bound<'_, PyAny>,
    op: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, input), category), weight)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(category.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(weight.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weight = weight.as_array();
      let weight = weight.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_group_reduce(&ctx, r, input, category, weight, op).map_err(|e| e.into())
    } else if let Some((((mut r, input), category), weight)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(category.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(weight.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weight = weight.as_array();
      let weight = weight.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_group_reduce(&ctx, r, input, category, weight, op).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Ordinal rank (1..n) with `tiebreak` deciding equal values; `ascending == 0`
  #[pyfunction]
  fn ft_ordinal_rank<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    mask: &'py Bound<'_, PyAny>,
    tiebreak: &'py Bound<'_, PyAny>,
    ascending: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, input), mask), tiebreak)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(tiebreak.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let tiebreak = tiebreak.as_array();
      let tiebreak = tiebreak.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_ordinal_rank(&ctx, r, input, mask, tiebreak, ascending).map_err(|e| e.into())
    } else if let Some((((mut r, input), mask), tiebreak)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(tiebreak.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let tiebreak = tiebreak.as_array();
      let tiebreak = tiebreak.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_ordinal_rank(&ctx, r, input, mask, tiebreak, ascending).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Cross-sectional percentage rank: `rank / valid_count - 0.5`.
  #[pyfunction]
  fn ft_rank<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_rank(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ft_rank(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ft_rank(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ft_rank(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Cross-sectional percentage rank restricted to an eligibility mask.
  #[pyfunction]
  fn ft_rank_masked<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    mask: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), mask)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_rank_masked(&ctx, r, input, mask).map_err(|e| e.into())
    } else if let Some(((mut r, input), mask)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_rank_masked(&ctx, r, input, mask).map_err(|e| e.into())
    } else if let Some(((r, input), mask)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(mask.cast::<PyList>().ok()) {
      if r.len() != input.len() || mask.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), mask)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(mask.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mask = mask.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(mask.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let mask = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_rank_masked(&ctx, r, input, mask).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), mask)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(mask.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mask = mask.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(mask.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let mask = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_rank_masked(&ctx, r, input, mask).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Cross-sectional OLS residualization on up to three exposures.
  #[pyfunction]
  fn ft_residualize<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    signal: &'py Bound<'_, PyAny>,
    exposure1: &'py Bound<'_, PyAny>,
    exposure2: &'py Bound<'_, PyAny>,
    exposure3: &'py Bound<'_, PyAny>,
    mask: &'py Bound<'_, PyAny>,
    exposure_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, signal), exposure1), exposure2), exposure3), mask)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(signal.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(exposure1.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(exposure2.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(exposure3.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let signal = signal.as_array();
      let signal = signal.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure1 = exposure1.as_array();
      let exposure1 = exposure1.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure2 = exposure2.as_array();
      let exposure2 = exposure2.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure3 = exposure3.as_array();
      let exposure3 = exposure3.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_residualize(&ctx, r, signal, exposure1, exposure2, exposure3, mask, exposure_count).map_err(|e| e.into())
    } else if let Some((((((mut r, signal), exposure1), exposure2), exposure3), mask)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(signal.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(exposure1.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(exposure2.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(exposure3.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(mask.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let signal = signal.as_array();
      let signal = signal.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure1 = exposure1.as_array();
      let exposure1 = exposure1.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure2 = exposure2.as_array();
      let exposure2 = exposure2.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let exposure3 = exposure3.as_array();
      let exposure3 = exposure3.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let mask = mask.as_array();
      let mask = mask.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_residualize(&ctx, r, signal, exposure1, exposure2, exposure3, mask, exposure_count).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Run a compiled plan over `(groups, rows)` slot panels.
  #[pyfunction]
  fn ft_run_plan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    slots: &'py Bound<'_, PyAny>,
    table: &'py Bound<'_, PyAny>,
    slot_count: usize,
    op_count: usize,
    leaf_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, slots), table)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(slots.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(table.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let slots = slots.as_array();
      let slots = slots.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let table = table.as_array();
      let table = table.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_run_plan(&ctx, r, slots, table, slot_count, op_count, leaf_count).map_err(|e| e.into())
    } else if let Some(((mut r, slots), table)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(slots.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(table.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let slots = slots.as_array();
      let slots = slots.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let table = table.as_array();
      let table = table.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_run_plan(&ctx, r, slots, table, slot_count, op_count, leaf_count).map_err(|e| e.into())
    } else if let Some(((r, slots), table)) = r.cast::<PyList>().ok().zip(slots.cast::<PyList>().ok()).zip(table.cast::<PyList>().ok()) {
      if r.len() != slots.len() || table.len() != slots.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, slots), table)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(slots.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(table.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let slots = slots.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let table = table.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(slots.into_par_iter()).zip(table.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let slots = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let table = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_run_plan(&ctx, r, slots, table, slot_count, op_count, leaf_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, slots), table)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(slots.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(table.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let slots = slots.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let table = table.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(slots.into_par_iter()).zip(table.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let slots = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let table = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_run_plan(&ctx, r, slots, table, slot_count, op_count, leaf_count).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Scope-partitioned expanding aggregation with `min_count` valid observations.
  #[pyfunction]
  fn ft_scope_agg<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    keys: &'py Bound<'_, PyAny>,
    min_count: usize,
    op: usize,
    quantile: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), keys)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(keys.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let keys = keys.as_array();
      let keys = keys.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_scope_agg(&ctx, r, input, keys, min_count, op, quantile).map_err(|e| e.into())
    } else if let Some(((mut r, input), keys)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(keys.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let keys = keys.as_array();
      let keys = keys.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_scope_agg(&ctx, r, input, keys, min_count, op, quantile as f32).map_err(|e| e.into())
    } else if let Some(((r, input), keys)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(keys.cast::<PyList>().ok()) {
      if r.len() != input.len() || keys.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), keys)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(keys.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let keys = keys.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(keys.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let keys = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_scope_agg(&ctx, r, input, keys, min_count, op, quantile).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), keys)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(keys.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let keys = keys.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(keys.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let keys = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_scope_agg(&ctx, r, input, keys, min_count, op, quantile as f32).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Prefix aggregation inside scope partitions with fixed `[start, end]` truncation.
  #[pyfunction]
  fn ft_scope_trunc<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    keys: &'py Bound<'_, PyAny>,
    trunc_start: usize,
    trunc_end: usize,
    min_count: usize,
    op: usize,
    quantile: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), keys)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(keys.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let keys = keys.as_array();
      let keys = keys.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_scope_trunc(&ctx, r, input, keys, trunc_start, trunc_end, min_count, op, quantile).map_err(|e| e.into())
    } else if let Some(((mut r, input), keys)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(keys.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let keys = keys.as_array();
      let keys = keys.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_scope_trunc(&ctx, r, input, keys, trunc_start, trunc_end, min_count, op, quantile as f32).map_err(|e| e.into())
    } else if let Some(((r, input), keys)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(keys.cast::<PyList>().ok()) {
      if r.len() != input.len() || keys.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), keys)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(keys.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let keys = keys.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(keys.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let keys = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_scope_trunc(&ctx, r, input, keys, trunc_start, trunc_end, min_count, op, quantile).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), keys)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(keys.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let keys = keys.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(keys.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let keys = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_scope_trunc(&ctx, r, input, keys, trunc_start, trunc_end, min_count, op, quantile as f32).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Cross-sectional Spearman correlation per timestamp.
  #[pyfunction]
  fn ft_spearman<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    left: &'py Bound<'_, PyAny>,
    right: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_spearman(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((mut r, left), right)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(left.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let left = left.as_array();
      let left = left.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right = right.as_array();
      let right = right.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_spearman(&ctx, r, left, right).map_err(|e| e.into())
    } else if let Some(((r, left), right)) = r.cast::<PyList>().ok().zip(left.cast::<PyList>().ok()).zip(right.cast::<PyList>().ok()) {
      if r.len() != left.len() || right.len() != left.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_spearman(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, left), right)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(left.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(right.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let left = left.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let right = right.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(left.into_par_iter()).zip(right.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let left = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let right = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ft_spearman(&ctx, r, left, right).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Target-weight sizing: target = weight * equity / (price * multiplier).
  #[pyfunction]
  fn ft_target_quantities<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    prices: &'py Bound<'_, PyAny>,
    multipliers: &'py Bound<'_, PyAny>,
    weights: &'py Bound<'_, PyAny>,
    current: &'py Bound<'_, PyAny>,
    lot_sizes: &'py Bound<'_, PyAny>,
    equity: f64,
    round_policy: usize,
    mode: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, prices), multipliers), weights), current), lot_sizes)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(prices.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(multipliers.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(weights.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(current.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(lot_sizes.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let prices = prices.as_array();
      let prices = prices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let multipliers = multipliers.as_array();
      let multipliers = multipliers.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weights = weights.as_array();
      let weights = weights.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let current = current.as_array();
      let current = current.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lot_sizes = lot_sizes.as_array();
      let lot_sizes = lot_sizes.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_target_quantities(&ctx, r, prices, multipliers, weights, current, lot_sizes, equity, round_policy, mode).map_err(|e| e.into())
    } else if let Some((((((mut r, prices), multipliers), weights), current), lot_sizes)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(prices.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(multipliers.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(weights.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(current.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(lot_sizes.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let prices = prices.as_array();
      let prices = prices.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let multipliers = multipliers.as_array();
      let multipliers = multipliers.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let weights = weights.as_array();
      let weights = weights.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let current = current.as_array();
      let current = current.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let lot_sizes = lot_sizes.as_array();
      let lot_sizes = lot_sizes.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_target_quantities(&ctx, r, prices, multipliers, weights, current, lot_sizes, equity as f32, round_policy, mode).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Cross-sectional z-score with sample standard deviation (ddof=1).
  #[pyfunction]
  fn ft_zscore<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ft_zscore(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ft_zscore(&ctx, r, input).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ft_zscore(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ft_zscore(&ctx, r, input).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Forward split and dividend adjustment
  #[pyfunction]
  fn fw_split<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    price: &'py Bound<'_, PyAny>,
    dividend: &'py Bound<'_, PyAny>,
    transfer_shares: &'py Bound<'_, PyAny>,
    right_shares: &'py Bound<'_, PyAny>,
    right_price: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fw_split(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fw_split(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Forward split factor calculation
  #[pyfunction]
  fn fw_split_factor<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    price: &'py Bound<'_, PyAny>,
    dividend: &'py Bound<'_, PyAny>,
    transfer_shares: &'py Bound<'_, PyAny>,
    right_shares: &'py Bound<'_, PyAny>,
    right_price: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fw_split_factor(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else if let Some((((((mut r, price), dividend), transfer_shares), right_shares), right_price)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(price.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(dividend.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(transfer_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_shares.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(right_price.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let price = price.as_array();
      let price = price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let dividend = dividend.as_array();
      let dividend = dividend.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let transfer_shares = transfer_shares.as_array();
      let transfer_shares = transfer_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_shares = right_shares.as_array();
      let right_shares = right_shares.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let right_price = right_price.as_array();
      let right_price = right_price.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_fw_split_factor(&ctx, r, price, dividend, transfer_shares, right_shares, right_price).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate rank percentage within each category group at each time step
  #[pyfunction]
  fn group_rank<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    category: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_group_rank(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_group_rank(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((r, category), input)) = r.cast::<PyList>().ok().zip(category.cast::<PyList>().ok()).zip(input.cast::<PyList>().ok()) {
      if r.len() != category.len() || input.len() != category.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_group_rank(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_group_rank(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate Z-Score within each category group at each time step
  #[pyfunction]
  fn group_zscore<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    category: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_group_zscore(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_group_zscore(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((r, category), input)) = r.cast::<PyList>().ok().zip(category.cast::<PyList>().ok()).zip(input.cast::<PyList>().ok()) {
      if r.len() != category.len() || input.len() != category.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_group_zscore(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_group_zscore(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Find highest value in a preceding `periods` window
  #[pyfunction]
  fn hhv<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhv(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_hhv(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_hhv(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_hhv(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Find highest value in a preceding variable `periods` window
  #[pyfunction]
  fn hhv_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhv_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhv_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_hhv_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_hhv_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// The number of periods that have passed since the array reached its `periods` period high
  #[pyfunction]
  fn hhvbars<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhvbars(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_hhvbars(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_hhvbars(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_hhvbars(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// The number of periods that have passed since the array reached its variable `periods` period high
  #[pyfunction]
  fn hhvbars_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_hhvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_hhvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_hhvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Linear Regression Intercept
  #[pyfunction]
  fn intercept<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_intercept(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_intercept(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_intercept(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_intercept(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate rolling sample excess Kurtosis over a moving window
  #[pyfunction]
  fn kurtosis<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_kurtosis(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_kurtosis(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_kurtosis(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_kurtosis(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Count consecutive periods where condition is true up to the current bar
  #[pyfunction]
  fn last<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_last(&ctx, r, condition).map_err(|e| e.into())
    } else if let Some((mut r, condition)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
    {
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let condition = condition.as_array();
      let condition = condition
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_last(&ctx, r, condition).map_err(|e| e.into())
    } else if let Some((r, condition)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != condition.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array output and bool input
      if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_last(&ctx, r, condition).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array output
      } else if let Some((mut r, condition)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let condition = condition.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(condition.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let condition = input.as_slice();
            if let Some((r, condition)) = r.zip(condition) {
              ta_last(&ctx, r, condition).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling OLS R-squared against the bar index over the trailing `periods` window.
  #[pyfunction]
  fn linreg_r2<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_linreg_r2(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_linreg_r2(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_r2(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_r2(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling OLS residual standard deviation against the bar index.
  #[pyfunction]
  fn linreg_resid_std<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_linreg_resid_std(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_linreg_resid_std(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_resid_std(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_resid_std(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling OLS slope against the bar index over the trailing `periods` window.
  #[pyfunction]
  fn linreg_slope<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_linreg_slope(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_linreg_slope(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_slope(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_slope(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling OLS slope t-statistic against the bar index over the trailing window.
  #[pyfunction]
  fn linreg_tstat<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_linreg_tstat(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_linreg_tstat(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_tstat(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_linreg_tstat(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Find lowest value in a preceding `periods` window
  #[pyfunction]
  fn llv<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llv(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_llv(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_llv(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_llv(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Find lowest value in a preceding variable `periods` window
  #[pyfunction]
  fn llv_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llv_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llv_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_llv_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_llv_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// The number of periods that have passed since the array reached its periods period low
  #[pyfunction]
  fn llvbars<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llvbars(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_llvbars(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_llvbars(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_llvbars(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// The number of periods that have passed since the array reached its variable `periods` period low
  #[pyfunction]
  fn llvbars_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_llvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_llvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_llvbars_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// For 2 arrays A and B, return true if previous N periods A < B, Current A >= B
  #[pyfunction]
  fn longcross<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
    n: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, bool>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_longcross(&ctx, r, a, b, n).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected bool, float, float)")) }
  }
  /// Linear Weighted Moving Average
  #[pyfunction]
  fn lwma<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_lwma(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_lwma(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_lwma(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_lwma(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Linear Weighted Moving Average with variable periods
  #[pyfunction]
  fn lwma_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_lwma_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_lwma_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_lwma_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_lwma_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Simple Moving Average, also known as arithmetic moving average
  #[pyfunction]
  fn ma<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ma(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ma(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ma(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ma(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Simple Moving Average with variable periods
  #[pyfunction]
  fn ma_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ma_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ma_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ma_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ma_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Rolling median absolute deviation: median(|x - median(window)|).
  #[pyfunction]
  fn mad<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_mad(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_mad(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_mad(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_mad(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate element-wise maximum of two arrays
  #[pyfunction]
  fn max<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_max(&ctx, r, a, b).map_err(|e| e.into())
    } else if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_max(&ctx, r, a, b).map_err(|e| e.into())
    } else if let Some(((r, a), b)) = r.cast::<PyList>().ok().zip(a.cast::<PyList>().ok()).zip(b.cast::<PyList>().ok()) {
      if r.len() != a.len() || b.len() != a.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let a = a.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let b = b.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(a.into_par_iter()).zip(b.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_max(&ctx, r, a, b).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let a = a.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let b = b.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(a.into_par_iter()).zip(b.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_max(&ctx, r, a, b).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Rolling Maximum Drawdown.
  #[pyfunction]
  fn max_drawdown<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_max_drawdown(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_max_drawdown(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_max_drawdown(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_max_drawdown(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling maximum that skips missing observations.
  #[pyfunction]
  fn max_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_max_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_max_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_max_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_max_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling mean that skips missing observations; NaN until `min_count` valid points.
  #[pyfunction]
  fn mean_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_mean_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_mean_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_mean_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_mean_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling median with an explicit minimum valid count.
  #[pyfunction]
  fn median<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_median(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_median(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_median(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_median(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate element-wise minimum of two arrays
  #[pyfunction]
  fn min<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_min(&ctx, r, a, b).map_err(|e| e.into())
    } else if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_min(&ctx, r, a, b).map_err(|e| e.into())
    } else if let Some(((r, a), b)) = r.cast::<PyList>().ok().zip(a.cast::<PyList>().ok()).zip(b.cast::<PyList>().ok()) {
      if r.len() != a.len() || b.len() != a.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let a = a.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let b = b.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(a.into_par_iter()).zip(b.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_min(&ctx, r, a, b).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let a = a.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let b = b.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(a.into_par_iter()).zip(b.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_min(&ctx, r, a, b).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate rolling min-max difference (range) over a moving window
  #[pyfunction]
  fn min_max_diff<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_min_max_diff(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_min_max_diff(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_min_max_diff(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_min_max_diff(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling minimum that skips missing observations.
  #[pyfunction]
  fn min_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_min_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_min_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_min_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_min_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate rolling k-th central moment over a moving window
  #[pyfunction]
  fn moment<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    k: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_moment(&ctx, r, input, periods, k).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_moment(&ctx, r, input, periods, k).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_moment(&ctx, r, input, periods, k).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_moment(&ctx, r, input, periods, k).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Neutralize the effect of a categorical variable on a numeric variable
  #[pyfunction]
  fn neutralize<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    category: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_neutralize(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((mut r, category), input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(category.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let category = category.as_array();
      let category = category.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_neutralize(&ctx, r, category, input).map_err(|e| e.into())
    } else if let Some(((r, category), input)) = r.cast::<PyList>().ok().zip(category.cast::<PyList>().ok()).zip(input.cast::<PyList>().ok()) {
      if r.len() != category.len() || input.len() != category.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_neutralize(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, category), input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(category.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let category = category.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(category.into_par_iter()).zip(input.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let category = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let input = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_neutralize(&ctx, r, category, input).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate product of values in preceding `periods` window
  #[pyfunction]
  fn product<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_product(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_product(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_product(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_product(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate rolling quantile over a moving window
  #[pyfunction]
  fn quantile<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    q: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_quantile(&ctx, r, input, periods, q).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_quantile(&ctx, r, input, periods, q as f32).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_quantile(&ctx, r, input, periods, q).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_quantile(&ctx, r, input, periods, q as f32).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling quantile with linear interpolation and NaN skipping.
  #[pyfunction]
  fn quantile_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
    q: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_quantile_nan(&ctx, r, input, periods, min_count, q).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_quantile_nan(&ctx, r, input, periods, min_count, q as f32).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_quantile_nan(&ctx, r, input, periods, min_count, q).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_quantile_nan(&ctx, r, input, periods, min_count, q as f32).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate rank in a sliding window with size `periods`
  #[pyfunction]
  fn rank<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_rank(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_rank(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_rank(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_rank(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// For 2 arrays A and B, return true if A[i-1] > B[i-1] and A[i] <= B[i]
  #[pyfunction]
  fn rcross<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, bool>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_rcross(&ctx, r, a, b).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected bool, float, float)")) }
  }
  /// Right shift input array by `periods`, r[i] = input[i - periods]
  #[pyfunction]
  fn r#ref<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ref(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_ref(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ref(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_ref(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Right shift input array by variable `periods`, r[i] = input[i - periods[i]]
  #[pyfunction]
  fn ref_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ref_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), periods)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(periods.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let periods = periods.as_array();
      let periods = periods.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_ref_v(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some(((r, input), periods)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(periods.cast::<PyList>().ok()) {
      if r.len() != input.len() || periods.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ref_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), periods)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(periods.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let periods = periods.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(periods.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let periods = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_ref_v(&ctx, r, input, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Calculate Regression Coefficient (Beta) of Y on X over a moving window
  #[pyfunction]
  fn regbeta<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    y: &'py Bound<'_, PyAny>,
    x: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, y), x)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(y.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(x.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_regbeta(&ctx, r, y, x, periods).map_err(|e| e.into())
    } else if let Some(((mut r, y), x)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(y.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(x.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_regbeta(&ctx, r, y, x, periods).map_err(|e| e.into())
    } else if let Some(((r, y), x)) = r.cast::<PyList>().ok().zip(y.cast::<PyList>().ok()).zip(x.cast::<PyList>().ok()) {
      if r.len() != y.len() || x.len() != y.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, y), x)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(y.into_par_iter()).zip(x.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let y = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let x = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_regbeta(&ctx, r, y, x, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, y), x)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(y.into_par_iter()).zip(x.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let y = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let x = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_regbeta(&ctx, r, y, x, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// Calculate Regression Residual of Y on X over a moving window
  #[pyfunction]
  fn regresi<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    y: &'py Bound<'_, PyAny>,
    x: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, y), x)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(y.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(x.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_regresi(&ctx, r, y, x, periods).map_err(|e| e.into())
    } else if let Some(((mut r, y), x)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(y.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(x.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let y = y.as_array();
      let y = y.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let x = x.as_array();
      let x = x.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_regresi(&ctx, r, y, x, periods).map_err(|e| e.into())
    } else if let Some(((r, y), x)) = r.cast::<PyList>().ok().zip(y.cast::<PyList>().ok()).zip(x.cast::<PyList>().ok()) {
      if r.len() != y.len() || x.len() != y.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, y), x)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        // ... list iter logic ...
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(y.into_par_iter()).zip(x.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let y = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let x = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_regresi(&ctx, r, y, x, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, y), x)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(y.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(x.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let y = y.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let x = x.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(y.into_par_iter()).zip(x.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let y = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let x = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_regresi(&ctx, r, y, x, periods).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input")) }
  }
  /// For 2 arrays A and B, return true if previous N periods A > B, Current A <= B
  #[pyfunction]
  fn rlongcross<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
    n: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, a), b)) = r
      .extract::<PyReadwriteArray1<'py, bool>>() .ok()
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_rlongcross(&ctx, r, a, b, n).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected bool, float, float)")) }
  }
  /// Conditional cumulative add: r[t] = r[t-1] + (cond[t] ? input[t] : 0)
  #[pyfunction]
  fn scan_add<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_scan_add(&ctx, r, input, condition).map_err(|e| e.into())
    } else if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_scan_add(&ctx, r, input, condition).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected float, float, bool)")) }
  }
  /// Conditional cumulative multiply: r[t] = r[t-1] * (cond[t] ? input[t] : 1)
  #[pyfunction]
  fn scan_mul<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_scan_mul(&ctx, r, input, condition).map_err(|e| e.into())
    } else if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_scan_mul(&ctx, r, input, condition).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected float, float, bool)")) }
  }
  /// Rolling Sharpe Ratio of returns.
  #[pyfunction]
  fn sharpe<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sharpe(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_sharpe(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sharpe(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sharpe(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling skewness matching pandas `rolling(periods, min_periods=min_count).skew()`.
  #[pyfunction]
  fn skew_exact<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_skew_exact(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_skew_exact(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_skew_exact(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_skew_exact(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate rolling sample Skewness over a moving window
  #[pyfunction]
  fn skewness<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_skewness(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_skewness(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_skewness(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_skewness(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Linear Regression Slope
  #[pyfunction]
  fn slope<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_slope(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_slope(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_slope(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_slope(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Exponential Moving Average (variant of well-known EMA) weight = m / n
  #[pyfunction]
  fn sma<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    n: usize,
    m: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sma(&ctx, r, input, n, m).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_sma(&ctx, r, input, n, m).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sma(&ctx, r, input, n, m).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sma(&ctx, r, input, n, m).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Exponential Moving Average (variant of well-known EMA) weight = m / n with variable periods
  #[pyfunction]
  fn sma_v<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    ns: &'py Bound<'_, PyAny>,
    m: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), ns)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(ns.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ns = ns.as_array();
      let ns = ns.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sma_v(&ctx, r, input, ns, m).map_err(|e| e.into())
    } else if let Some(((mut r, input), ns)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(ns.extract::<PyReadonlyArray1<'py, usize>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let ns = ns.as_array();
      let ns = ns.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sma_v(&ctx, r, input, ns, m).map_err(|e| e.into())
    } else if let Some(((r, input), ns)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()).zip(ns.cast::<PyList>().ok()) {
      if r.len() != input.len() || ns.len() != input.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, input), ns)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(ns.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let ns = ns.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(ns.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let ns = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_sma_v(&ctx, r, input, ns, m).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else if let Some(((mut r, input), ns)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(ns.extract::<Vec<PyReadonlyArray1<'py, usize>>>().ok()) {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let ns = ns.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter().zip(input.into_par_iter()).zip(ns.into_par_iter())
          .map(|((mut out, a), b)| {
            let r = out.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
            let input = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            let ns = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
            ta_sma_v(&ctx, r, input, ns, m).map_err(|e| e.into())
          }).collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) { Some(e) => e, None => Ok(()) }
      } else { Err(PyValueError::new_err("invalid input list")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, float, int)")) }
  }
  /// Rolling sample standard deviation (ddof=1) that skips missing observations.
  #[pyfunction]
  fn std_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_std_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_std_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_std_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_std_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate Standard Deviation over a moving window
  #[pyfunction]
  fn stddev<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_stddev(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_stddev(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_stddev(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_stddev(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate sum of values in preceding `periods` window
  #[pyfunction]
  fn sum<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sum(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_sum(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sum(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sum(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling sum that skips missing observations.
  #[pyfunction]
  fn sum_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sum_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_sum_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sum_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sum_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate number of periods (bars) backwards until the sum of values is greater than or equal to `amount`
  #[pyfunction]
  fn sumbars<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    amount: f64,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sumbars(&ctx, r, input, amount).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_sumbars(&ctx, r, input, amount as f32).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sumbars(&ctx, r, input, amount).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_sumbars(&ctx, r, input, amount as f32).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate sum of values in preceding `periods` window where `condition` is true
  #[pyfunction]
  fn sumif<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f64>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sumif(&ctx, r, input, condition, periods).map_err(|e| e.into())
    } else if let Some(((mut r, input), condition)) = r
      .extract::<PyReadwriteArray1<'py, f32>>() .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_sumif(&ctx, r, input, condition, periods).map_err(|e| e.into())
    } else { Err(PyValueError::new_err("invalid input (expected float, float, bool)")) }
  }
  /// Calculate Variance over a moving window
  #[pyfunction]
  fn var<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_var(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_var(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_var(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_var(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Rolling sample variance (ddof=1) that skips missing observations.
  #[pyfunction]
  fn var_nan<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
    min_count: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_var_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_var_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_var_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_var_nan(&ctx, r, input, periods, min_count).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Calculate weighted delay (exponentially weighted lag)
  #[pyfunction]
  fn weighted_delay<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_weighted_delay(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_weighted_delay(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_weighted_delay(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_weighted_delay(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }
  /// Choose elements from a or b depending on condition
  #[pyfunction]
  fn r#where<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    condition: &'py Bound<'_, PyAny>,
    a: &'py Bound<'_, PyAny>,
    b: &'py Bound<'_, PyAny>,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((((mut r, condition), a), b)) = r
      .extract::<PyReadwriteArray1<'py, f64>>().ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
      .zip(a.extract::<PyReadonlyArray1<'py, f64>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f64>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_where(&ctx, r, condition, a, b).map_err(|e| e.into())
    } else if let Some((((mut r, condition), a), b)) = r
      .extract::<PyReadwriteArray1<'py, f32>>().ok()
      .zip(condition.extract::<PyReadonlyArray1<'py, bool>>().ok())
      .zip(a.extract::<PyReadonlyArray1<'py, f32>>().ok())
      .zip(b.extract::<PyReadonlyArray1<'py, f32>>().ok()) {
      let mut r = r.as_array_mut();
      let r = r.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let condition = condition.as_array();
      let condition = condition.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let a = a.as_array();
      let a = a.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      let b = b.as_array();
      let b = b.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_where(&ctx, r, condition, a, b).map_err(|e| e.into())
    } else if let Some((((r, condition), a), b)) = r.cast::<PyList>().ok().zip(condition.cast::<PyList>().ok()).zip(a.cast::<PyList>().ok()).zip(b.cast::<PyList>().ok()) {
      if r.len() != condition.len() || r.len() != a.len() || r.len() != b.len() { return Err(PyValueError::new_err("length mismatch")); }
      if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok()) {
        let condition = condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>()?;
        ctx._groups = r.len() as u32;
        for i in 0..r.len() {
          let mut r_arr = r[i].as_array_mut();
          let r_slice = r_arr.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
          let a_arr = condition[i].as_array();
          let a_slice = a_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          let b_arr = a[i].as_array();
          let b_slice = b_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          let c_arr = b[i].as_array();
          let c_slice = c_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          ta_where(&ctx, r_slice, a_slice, b_slice, c_slice).map_err(|e| PyErr::from(e))?;
        }
        Ok(())
      } else if let Some(((mut r, a), b)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>().ok()
        .zip(a.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
        .zip(b.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok()) {
        let condition = condition.extract::<Vec<PyReadonlyArray1<'py, bool>>>()?;
        ctx._groups = r.len() as u32;
        for i in 0..r.len() {
          let mut r_arr = r[i].as_array_mut();
          let r_slice = r_arr.as_slice_mut().ok_or(PyValueError::new_err("failed to get mutable slice"))?;
          let a_arr = condition[i].as_array();
          let a_slice = a_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          let b_arr = a[i].as_array();
          let b_slice = b_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          let c_arr = b[i].as_array();
          let c_slice = c_arr.as_slice().ok_or(PyValueError::new_err("failed to get slice"))?;
          ta_where(&ctx, r_slice, a_slice, b_slice, c_slice).map_err(|e| PyErr::from(e))?;
        }
        Ok(())
      } else { Err(PyValueError::new_err("invalid list input (expected float, bool, float, float)")) }
    } else { Err(PyValueError::new_err("invalid input (expected float, bool, float, float)")) }
  }
  /// Calculate rolling Z-Score over a moving window
  #[pyfunction]
  fn zscore<'py>(
    py: Python<'py>,
    r: &'py Bound<'_, PyAny>,
    input: &'py Bound<'_, PyAny>,
    periods: usize,
  ) -> PyResult<()> {
    // 1. get context
    #[allow(unused_mut)]
    let mut ctx = ctx(py);
    // 2. check input type and do dispatch
    if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f64>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f64>>().ok())
    {
      // input is f64 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("failed to get mutable slice"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("failed to get slice"))?;
      ta_zscore(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((mut r, input)) = r
      .extract::<PyReadwriteArray1<'py, f32>>()
      .ok()
      .zip(input.extract::<PyReadonlyArray1<'py, f32>>().ok())
    {
      // input is f32 array
      let mut r = r.as_array_mut();
      let r = r
        .as_slice_mut()
        .ok_or(PyValueError::new_err("invalid input"))?;
      let input = input.as_array();
      let input = input
        .as_slice()
        .ok_or(PyValueError::new_err("invalid input"))?;
      ta_zscore(&ctx, r, input, periods).map_err(|e| e.into())
    } else if let Some((r, input)) = r.cast::<PyList>().ok().zip(input.cast::<PyList>().ok()) {
      // input is list of arrays
      // each array is a group, ensure groups is set to 1
      ctx._groups = 1;
      if r.len() != input.len() {
        return Err(PyValueError::new_err("length mismatch"));
      }
      // check if each array is f64 array
      if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f64>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f64>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_zscore(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      // check if each array is f32 array
      } else if let Some((mut r, input)) = r
        .extract::<Vec<PyReadwriteArray1<'py, f32>>>()
        .ok()
        .zip(input.extract::<Vec<PyReadonlyArray1<'py, f32>>>().ok())
      {
        let r = r.iter_mut().map(|x| x.as_array_mut()).collect::<Vec<_>>();
        let input = input.iter().map(|x| x.as_array()).collect::<Vec<_>>();
        let mut _r = vec![];
        r.into_par_iter()
          .zip(input.into_par_iter())
          .map(|(mut out, input)| {
            let r = out.as_slice_mut();
            let input = input.as_slice();
            if let Some((r, input)) = r.zip(input) {
              ta_zscore(&ctx, r, input, periods).map_err(|e| e.into())
            } else {
              Err(PyValueError::new_err("invalid input"))
            }
          })
          .collect_into_vec(&mut _r);
        match _r.into_iter().find(|x| x.is_err()) {
          Some(e) => e,
          None => Ok(()),
        }
      } else {
        Err(PyValueError::new_err("invalid input"))
      }
    } else {
      Err(PyValueError::new_err("invalid input"))
    }
  }

pub fn register_functions(m: &Bound<'_, PyModule>) -> PyResult<()> {
  m.add_function(wrap_pyfunction!(abs, m)?)?;
  m.add_function(wrap_pyfunction!(all, m)?)?;
  m.add_function(wrap_pyfunction!(alpha, m)?)?;
  m.add_function(wrap_pyfunction!(any, m)?)?;
  m.add_function(wrap_pyfunction!(argmax, m)?)?;
  m.add_function(wrap_pyfunction!(argmax_raw, m)?)?;
  m.add_function(wrap_pyfunction!(argmin, m)?)?;
  m.add_function(wrap_pyfunction!(argmin_raw, m)?)?;
  m.add_function(wrap_pyfunction!(backfill, m)?)?;
  m.add_function(wrap_pyfunction!(backset, m)?)?;
  m.add_function(wrap_pyfunction!(barslast, m)?)?;
  m.add_function(wrap_pyfunction!(barssince, m)?)?;
  m.add_function(wrap_pyfunction!(beta, m)?)?;
  m.add_function(wrap_pyfunction!(bins, m)?)?;
  m.add_function(wrap_pyfunction!(bw_split, m)?)?;
  m.add_function(wrap_pyfunction!(bw_split_factor, m)?)?;
  m.add_function(wrap_pyfunction!(cc_rank, m)?)?;
  m.add_function(wrap_pyfunction!(cc_zscore, m)?)?;
  m.add_function(wrap_pyfunction!(corr, m)?)?;
  m.add_function(wrap_pyfunction!(corr2, m)?)?;
  m.add_function(wrap_pyfunction!(corr_nan, m)?)?;
  m.add_function(wrap_pyfunction!(count, m)?)?;
  m.add_function(wrap_pyfunction!(count_nans, m)?)?;
  m.add_function(wrap_pyfunction!(count_v, m)?)?;
  m.add_function(wrap_pyfunction!(cov, m)?)?;
  m.add_function(wrap_pyfunction!(cov_nan, m)?)?;
  m.add_function(wrap_pyfunction!(cross, m)?)?;
  m.add_function(wrap_pyfunction!(dma, m)?)?;
  m.add_function(wrap_pyfunction!(dma_v, m)?)?;
  m.add_function(wrap_pyfunction!(ema_adjust, m)?)?;
  m.add_function(wrap_pyfunction!(ema_v, m)?)?;
  m.add_function(wrap_pyfunction!(entropy, m)?)?;
  m.add_function(wrap_pyfunction!(filter, m)?)?;
  m.add_function(wrap_pyfunction!(fret, m)?)?;
  m.add_function(wrap_pyfunction!(ft_average_cost_chain, m)?)?;
  m.add_function(wrap_pyfunction!(ft_bar_visibility, m)?)?;
  m.add_function(wrap_pyfunction!(ft_corr, m)?)?;
  m.add_function(wrap_pyfunction!(ft_cov, m)?)?;
  m.add_function(wrap_pyfunction!(ft_curve_fit, m)?)?;
  m.add_function(wrap_pyfunction!(ft_curve_pair, m)?)?;
  m.add_function(wrap_pyfunction!(ft_dynamic_arg, m)?)?;
  m.add_function(wrap_pyfunction!(ft_dynamic_mask, m)?)?;
  m.add_function(wrap_pyfunction!(ft_event_order, m)?)?;
  m.add_function(wrap_pyfunction!(ft_exec_positions, m)?)?;
  m.add_function(wrap_pyfunction!(ft_exec_schedule_ts, m)?)?;
  m.add_function(wrap_pyfunction!(ft_group, m)?)?;
  m.add_function(wrap_pyfunction!(ft_group_reduce, m)?)?;
  m.add_function(wrap_pyfunction!(ft_ordinal_rank, m)?)?;
  m.add_function(wrap_pyfunction!(ft_rank, m)?)?;
  m.add_function(wrap_pyfunction!(ft_rank_masked, m)?)?;
  m.add_function(wrap_pyfunction!(ft_residualize, m)?)?;
  m.add_function(wrap_pyfunction!(ft_run_plan, m)?)?;
  m.add_function(wrap_pyfunction!(ft_scope_agg, m)?)?;
  m.add_function(wrap_pyfunction!(ft_scope_trunc, m)?)?;
  m.add_function(wrap_pyfunction!(ft_spearman, m)?)?;
  m.add_function(wrap_pyfunction!(ft_target_quantities, m)?)?;
  m.add_function(wrap_pyfunction!(ft_zscore, m)?)?;
  m.add_function(wrap_pyfunction!(fw_split, m)?)?;
  m.add_function(wrap_pyfunction!(fw_split_factor, m)?)?;
  m.add_function(wrap_pyfunction!(group_rank, m)?)?;
  m.add_function(wrap_pyfunction!(group_zscore, m)?)?;
  m.add_function(wrap_pyfunction!(hhv, m)?)?;
  m.add_function(wrap_pyfunction!(hhv_v, m)?)?;
  m.add_function(wrap_pyfunction!(hhvbars, m)?)?;
  m.add_function(wrap_pyfunction!(hhvbars_v, m)?)?;
  m.add_function(wrap_pyfunction!(intercept, m)?)?;
  m.add_function(wrap_pyfunction!(kurtosis, m)?)?;
  m.add_function(wrap_pyfunction!(last, m)?)?;
  m.add_function(wrap_pyfunction!(linreg_r2, m)?)?;
  m.add_function(wrap_pyfunction!(linreg_resid_std, m)?)?;
  m.add_function(wrap_pyfunction!(linreg_slope, m)?)?;
  m.add_function(wrap_pyfunction!(linreg_tstat, m)?)?;
  m.add_function(wrap_pyfunction!(llv, m)?)?;
  m.add_function(wrap_pyfunction!(llv_v, m)?)?;
  m.add_function(wrap_pyfunction!(llvbars, m)?)?;
  m.add_function(wrap_pyfunction!(llvbars_v, m)?)?;
  m.add_function(wrap_pyfunction!(longcross, m)?)?;
  m.add_function(wrap_pyfunction!(lwma, m)?)?;
  m.add_function(wrap_pyfunction!(lwma_v, m)?)?;
  m.add_function(wrap_pyfunction!(ma, m)?)?;
  m.add_function(wrap_pyfunction!(ma_v, m)?)?;
  m.add_function(wrap_pyfunction!(mad, m)?)?;
  m.add_function(wrap_pyfunction!(max, m)?)?;
  m.add_function(wrap_pyfunction!(max_drawdown, m)?)?;
  m.add_function(wrap_pyfunction!(max_nan, m)?)?;
  m.add_function(wrap_pyfunction!(mean_nan, m)?)?;
  m.add_function(wrap_pyfunction!(median, m)?)?;
  m.add_function(wrap_pyfunction!(min, m)?)?;
  m.add_function(wrap_pyfunction!(min_max_diff, m)?)?;
  m.add_function(wrap_pyfunction!(min_nan, m)?)?;
  m.add_function(wrap_pyfunction!(moment, m)?)?;
  m.add_function(wrap_pyfunction!(neutralize, m)?)?;
  m.add_function(wrap_pyfunction!(product, m)?)?;
  m.add_function(wrap_pyfunction!(quantile, m)?)?;
  m.add_function(wrap_pyfunction!(quantile_nan, m)?)?;
  m.add_function(wrap_pyfunction!(rank, m)?)?;
  m.add_function(wrap_pyfunction!(rcross, m)?)?;
  m.add_function(wrap_pyfunction!(r#ref, m)?)?;
  m.add_function(wrap_pyfunction!(ref_v, m)?)?;
  m.add_function(wrap_pyfunction!(regbeta, m)?)?;
  m.add_function(wrap_pyfunction!(regresi, m)?)?;
  m.add_function(wrap_pyfunction!(rlongcross, m)?)?;
  m.add_function(wrap_pyfunction!(scan_add, m)?)?;
  m.add_function(wrap_pyfunction!(scan_mul, m)?)?;
  m.add_function(wrap_pyfunction!(sharpe, m)?)?;
  m.add_function(wrap_pyfunction!(skew_exact, m)?)?;
  m.add_function(wrap_pyfunction!(skewness, m)?)?;
  m.add_function(wrap_pyfunction!(slope, m)?)?;
  m.add_function(wrap_pyfunction!(sma, m)?)?;
  m.add_function(wrap_pyfunction!(sma_v, m)?)?;
  m.add_function(wrap_pyfunction!(std_nan, m)?)?;
  m.add_function(wrap_pyfunction!(stddev, m)?)?;
  m.add_function(wrap_pyfunction!(sum, m)?)?;
  m.add_function(wrap_pyfunction!(sum_nan, m)?)?;
  m.add_function(wrap_pyfunction!(sumbars, m)?)?;
  m.add_function(wrap_pyfunction!(sumif, m)?)?;
  m.add_function(wrap_pyfunction!(var, m)?)?;
  m.add_function(wrap_pyfunction!(var_nan, m)?)?;
  m.add_function(wrap_pyfunction!(weighted_delay, m)?)?;
  m.add_function(wrap_pyfunction!(r#where, m)?)?;
  m.add_function(wrap_pyfunction!(zscore, m)?)?;
  Ok(())
}
