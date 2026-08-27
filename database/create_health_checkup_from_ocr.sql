-- OCR로 확인된 건강검진 결과를 사용자 JWT와 RLS로 원자적 저장한다.
-- 작성자: 김진우

GRANT INSERT ON TABLE public.health_checkup_records TO authenticated;
GRANT INSERT ON TABLE public.health_checkup_results TO authenticated;

DROP POLICY IF EXISTS health_checkup_records_insert_own
    ON public.health_checkup_records;
CREATE POLICY health_checkup_records_insert_own
    ON public.health_checkup_records
    FOR INSERT
    TO authenticated
    WITH CHECK ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS health_checkup_results_insert_own
    ON public.health_checkup_results;
CREATE POLICY health_checkup_results_insert_own
    ON public.health_checkup_results
    FOR INSERT
    TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.health_checkup_records AS record
            WHERE record.record_id = health_checkup_results.record_id
              AND record.user_id = (SELECT auth.uid())
        )
    );

CREATE OR REPLACE FUNCTION public.create_health_checkup_from_ocr(
    p_measured_at date,
    p_results jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_user_id uuid := (SELECT auth.uid());
    v_record_id uuid;
    v_result_count integer;
    v_distinct_code_count integer;
    v_valid_code_count integer;
BEGIN
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION '사용자 인증이 필요합니다.' USING ERRCODE = '28000';
    END IF;
    IF p_measured_at IS NULL THEN
        RAISE EXCEPTION '검진일이 필요합니다.' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_results) IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_results) = 0 THEN
        RAISE EXCEPTION '한 개 이상의 검진 결과가 필요합니다.' USING ERRCODE = '22023';
    END IF;

    SELECT
        count(*),
        count(DISTINCT nullif(btrim(result ->> 'item_code'), '')),
        count(master.item_code)
    INTO v_result_count, v_distinct_code_count, v_valid_code_count
    FROM jsonb_array_elements(p_results) AS result
    LEFT JOIN public.master_checkup_item AS master
      ON master.item_code = nullif(btrim(result ->> 'item_code'), '');

    IF v_result_count <> v_distinct_code_count THEN
        RAISE EXCEPTION '검사항목 코드가 비어 있거나 중복되었습니다.'
            USING ERRCODE = '22023';
    END IF;
    IF v_result_count <> v_valid_code_count THEN
        RAISE EXCEPTION '등록되지 않은 검사항목 코드가 포함되어 있습니다.'
            USING ERRCODE = '23503';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_results) AS result
        WHERE nullif(btrim(result ->> 'value'), '') IS NULL
    ) THEN
        RAISE EXCEPTION '검사 결과값이 비어 있습니다.' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.health_checkup_records (user_id, measured_at)
    VALUES (v_user_id, p_measured_at)
    RETURNING record_id INTO v_record_id;

    INSERT INTO public.health_checkup_results (
        record_id,
        item_code,
        value,
        status
    )
    SELECT
        v_record_id,
        btrim(result ->> 'item_code'),
        btrim(result ->> 'value'),
        nullif(btrim(result ->> 'status'), '')
    FROM jsonb_array_elements(p_results) AS result;

    RETURN v_record_id;
END;
$$;

REVOKE ALL ON FUNCTION public.create_health_checkup_from_ocr(date, jsonb)
    FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.create_health_checkup_from_ocr(date, jsonb)
    TO authenticated;

COMMENT ON FUNCTION public.create_health_checkup_from_ocr(date, jsonb)
    IS '사용자가 확인한 OCR 건강검진 회차와 결과를 한 트랜잭션으로 저장';
