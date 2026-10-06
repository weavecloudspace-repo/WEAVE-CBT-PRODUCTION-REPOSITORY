"""Frozen initial CBT schema. Do not regenerate after model changes."""

from alembic import op

revision = "20261006_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE school_profiles (\n\tname VARCHAR(255) NOT NULL, \n\tinstitution_type VARCHAR(64), \n\ttimezone VARCHAR(128) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_school_profiles PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_school_profiles_source_deleted_at ON school_profiles (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE academic_sessions (\n\tname VARCHAR(255) NOT NULL, \n\tstatus VARCHAR(64) NOT NULL, \n\tis_current BOOLEAN DEFAULT false NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_sessions PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_sessions_is_current ON academic_sessions (is_current)"
    )
    op.execute(
        "CREATE INDEX ix_academic_sessions_current_status ON academic_sessions (is_current, status)"
    )
    op.execute("CREATE INDEX ix_academic_sessions_status ON academic_sessions (status)")
    op.execute(
        "CREATE INDEX ix_academic_sessions_source_deleted_at ON academic_sessions (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE academic_levels (\n\tname VARCHAR(255) NOT NULL, \n\tcategory VARCHAR(64) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tspecialization_required_from_term_position INTEGER, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_levels PRIMARY KEY (id), \n\tCONSTRAINT ck_academic_levels_position_nonnegative CHECK (position >= 0), \n\tCONSTRAINT ck_academic_levels_specialization_term_position CHECK (specialization_required_from_term_position IS NULL OR specialization_required_from_term_position BETWEEN 1 AND 3)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_levels_source_deleted_at ON academic_levels (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_academic_levels_category_position ON academic_levels (category, position)"
    )
    op.execute("CREATE INDEX ix_academic_levels_category ON academic_levels (category)")
    op.execute(
        "\nCREATE TABLE arm_labels (\n\tlabel VARCHAR(64) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_arm_labels PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_arm_labels_source_deleted_at ON arm_labels (source_deleted_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_arm_labels_current_label ON arm_labels (label) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "\nCREATE TABLE academic_subjects (\n\tname VARCHAR(255) NOT NULL, \n\tcode VARCHAR(64), \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_subjects PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_subjects_is_active ON academic_subjects (is_active)"
    )
    op.execute(
        "CREATE INDEX ix_academic_subjects_source_deleted_at ON academic_subjects (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE assessment_schemes (\n\tname VARCHAR(255) NOT NULL, \n\tstatus VARCHAR(64) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_assessment_schemes PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_assessment_schemes_source_deleted_at ON assessment_schemes (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_assessment_schemes_status ON assessment_schemes (status)"
    )
    op.execute(
        "\nCREATE TABLE academic_admins (\n\temail VARCHAR(255) NOT NULL, \n\tstatus VARCHAR(64) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_admins PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_admins_source_deleted_at ON academic_admins (source_deleted_at)"
    )
    op.execute("CREATE INDEX ix_academic_admins_status ON academic_admins (status)")
    op.execute("CREATE INDEX ix_academic_admins_email ON academic_admins (email)")
    op.execute(
        "\nCREATE TABLE academic_teachers (\n\tteacher_account_id UUID NOT NULL, \n\tfirst_name VARCHAR(255), \n\tlast_name VARCHAR(255), \n\tstaff_id VARCHAR(128), \n\tstatus VARCHAR(64) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_teachers PRIMARY KEY (id)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_teachers_source_deleted_at ON academic_teachers (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_academic_teachers_staff_id ON academic_teachers (staff_id)"
    )
    op.execute(
        "CREATE INDEX ix_academic_teachers_teacher_account_id ON academic_teachers (teacher_account_id)"
    )
    op.execute(
        "CREATE INDEX ix_academic_teachers_status_name ON academic_teachers (status, last_name, first_name)"
    )
    op.execute("CREATE INDEX ix_academic_teachers_status ON academic_teachers (status)")
    op.execute(
        "\nCREATE TABLE audit_events (\n\tactor_type VARCHAR(11) NOT NULL, \n\tactor_id UUID, \n\tactor_name VARCHAR(255), \n\tactor_role VARCHAR(64), \n\taction VARCHAR(128) NOT NULL, \n\toutcome VARCHAR(7) DEFAULT 'success' NOT NULL, \n\tentity_type VARCHAR(64), \n\tentity_id UUID, \n\tentity_label VARCHAR(255), \n\treason TEXT, \n\tmetadata_json JSONB, \n\trequest_id VARCHAR(128), \n\tclient_ip VARCHAR(45), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_audit_events PRIMARY KEY (id), \n\tCONSTRAINT audit_actor_type CHECK (actor_type IN ('local_actor', 'candidate', 'system')), \n\tCONSTRAINT audit_outcome CHECK (outcome IN ('success', 'denied', 'failed'))\n)\n\n"
    )
    op.execute("CREATE INDEX ix_audit_events_actor_type ON audit_events (actor_type)")
    op.execute("CREATE INDEX ix_audit_events_entity_id ON audit_events (entity_id)")
    op.execute("CREATE INDEX ix_audit_events_request_id ON audit_events (request_id)")
    op.execute(
        "CREATE INDEX ix_audit_events_entity_created ON audit_events (entity_type, entity_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events_actor_created ON audit_events (actor_type, actor_id, created_at)"
    )
    op.execute("CREATE INDEX ix_audit_events_entity_type ON audit_events (entity_type)")
    op.execute("CREATE INDEX ix_audit_events_actor_id ON audit_events (actor_id)")
    op.execute(
        "CREATE INDEX ix_audit_events_action_created ON audit_events (action, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events_outcome_created ON audit_events (outcome, created_at)"
    )
    op.execute("CREATE INDEX ix_audit_events_outcome ON audit_events (outcome)")
    op.execute("CREATE INDEX ix_audit_events_action ON audit_events (action)")
    op.execute(
        "\nCREATE TABLE local_actors (\n\tweave_actor_id VARCHAR(128) NOT NULL, \n\tweave_membership_id VARCHAR(128), \n\trole VARCHAR(64) NOT NULL, \n\temail VARCHAR(255) NOT NULL, \n\tdisplay_name VARCHAR(255) NOT NULL, \n\tis_active BOOLEAN NOT NULL, \n\tlast_weave_authenticated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_weave_revalidated_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_local_actors PRIMARY KEY (id), \n\tCONSTRAINT uq_local_actors_weave_actor_role UNIQUE (weave_actor_id, role), \n\tCONSTRAINT ck_local_actors_role_not_blank CHECK (char_length(trim(role)) > 0), \n\tCONSTRAINT ck_local_actors_email_not_blank CHECK (char_length(trim(email)) > 0)\n)\n\n"
    )
    op.execute("CREATE INDEX ix_local_actors_role ON local_actors (role)")
    op.execute("CREATE INDEX ix_local_actors_email ON local_actors (email)")
    op.execute(
        "CREATE INDEX ix_local_actors_role_active ON local_actors (role, is_active)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_local_actors_weave_membership_id ON local_actors (weave_membership_id)"
    )
    op.execute(
        "\nCREATE TABLE branding_states (\n\ttenant_id UUID NOT NULL, \n\tschool_name VARCHAR(255) NOT NULL, \n\tlogo_url TEXT, \n\tlogo_revision UUID, \n\tlogo_storage_key VARCHAR(512), \n\tlogo_mime_type VARCHAR(100), \n\tlogo_size_bytes BIGINT, \n\tlogo_sha256 VARCHAR(64), \n\tis_enabled BOOLEAN DEFAULT false NOT NULL, \n\tis_default_theme BOOLEAN DEFAULT true NOT NULL, \n\ttheme_version INTEGER DEFAULT 0 NOT NULL, \n\ttoken_schema_version INTEGER DEFAULT 1 NOT NULL, \n\tlight_tokens JSON NOT NULL, \n\tlast_synced_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_branding_states PRIMARY KEY (id), \n\tCONSTRAINT ck_branding_states_theme_version_nonnegative CHECK (theme_version >= 0), \n\tCONSTRAINT ck_branding_states_token_schema_version_positive CHECK (token_schema_version >= 1), \n\tCONSTRAINT ck_branding_states_logo_size_positive CHECK (logo_size_bytes IS NULL OR logo_size_bytes > 0), \n\tCONSTRAINT ck_branding_states_logo_cache_complete CHECK ((logo_storage_key IS NULL AND logo_mime_type IS NULL AND logo_size_bytes IS NULL AND logo_sha256 IS NULL) OR (logo_storage_key IS NOT NULL AND logo_mime_type IS NOT NULL AND logo_size_bytes IS NOT NULL AND logo_sha256 IS NOT NULL))\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_branding_states_tenant_id ON branding_states (tenant_id)"
    )
    op.execute(
        "\nCREATE TABLE cbt_runtime_states (\n\truntime_id UUID NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tlast_heartbeat_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tstopped_at TIMESTAMP WITH TIME ZONE, \n\tshutdown_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_cbt_runtime_states PRIMARY KEY (id), \n\tCONSTRAINT ck_cbt_runtime_states_heartbeat_after_start CHECK (last_heartbeat_at >= started_at), \n\tCONSTRAINT ck_cbt_runtime_states_stop_after_start CHECK (stopped_at IS NULL OR stopped_at >= started_at), \n\tCONSTRAINT ck_cbt_runtime_states_stop_after_heartbeat CHECK (stopped_at IS NULL OR stopped_at >= last_heartbeat_at), \n\tCONSTRAINT ck_cbt_runtime_states_shutdown_reason_requires_stop CHECK (stopped_at IS NOT NULL OR shutdown_reason IS NULL)\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_cbt_runtime_states_last_heartbeat_at ON cbt_runtime_states (last_heartbeat_at)"
    )
    op.execute(
        "CREATE INDEX ix_cbt_runtime_states_started_at ON cbt_runtime_states (started_at)"
    )
    op.execute(
        "CREATE INDEX ix_cbt_runtime_states_started_heartbeat ON cbt_runtime_states (started_at, last_heartbeat_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_cbt_runtime_states_runtime_id ON cbt_runtime_states (runtime_id)"
    )
    op.execute(
        "\nCREATE TABLE realtime_outbox_events (\n\taggregate_type VARCHAR(64) NOT NULL, \n\taggregate_id UUID NOT NULL, \n\tevent_type VARCHAR(128) NOT NULL, \n\tpayload JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tstatus VARCHAR(10) DEFAULT 'pending' NOT NULL, \n\tavailable_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tpublish_attempts INTEGER DEFAULT 0 NOT NULL, \n\tlast_publish_attempt_at TIMESTAMP WITH TIME ZONE, \n\tclaim_token UUID, \n\tclaimed_at TIMESTAMP WITH TIME ZONE, \n\tpublished_at TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_realtime_outbox_events PRIMARY KEY (id), \n\tCONSTRAINT ck_realtime_outbox_publish_attempts_nonnegative CHECK (publish_attempts >= 0), \n\tCONSTRAINT ck_realtime_outbox_error_length CHECK (last_error IS NULL OR char_length(last_error) <= 2048), \n\tCONSTRAINT ck_realtime_outbox_publishing_requires_claim CHECK ((status = 'publishing' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL) OR status <> 'publishing'), \n\tCONSTRAINT ck_realtime_outbox_published_at_matches_status CHECK (published_at IS NULL OR status = 'published'), \n\tCONSTRAINT ck_realtime_outbox_published_requires_timestamp CHECK (status <> 'published' OR published_at IS NOT NULL), \n\tCONSTRAINT outbox_event_status CHECK (status IN ('pending', 'publishing', 'published', 'failed'))\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_status ON realtime_outbox_events (status)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_claimed_at ON realtime_outbox_events (claimed_at)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_aggregate ON realtime_outbox_events (aggregate_type, aggregate_id)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_available_at ON realtime_outbox_events (available_at)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_aggregate_type ON realtime_outbox_events (aggregate_type)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_aggregate_id ON realtime_outbox_events (aggregate_id)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_dispatch ON realtime_outbox_events (status, available_at)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_event_type ON realtime_outbox_events (event_type)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_stale_claim ON realtime_outbox_events (status, claimed_at)"
    )
    op.execute(
        "CREATE INDEX ix_realtime_outbox_events_claim_token ON realtime_outbox_events (claim_token)"
    )
    op.execute(
        "\nCREATE TABLE sync_states (\n\tscope VARCHAR(64) NOT NULL, \n\tschema_version INTEGER DEFAULT 5 NOT NULL, \n\tcursor BIGINT DEFAULT 0 NOT NULL, \n\tbootstrap_snapshot_id UUID, \n\tbootstrap_completed_at TIMESTAMP WITH TIME ZONE, \n\tlast_attempted_at TIMESTAMP WITH TIME ZONE, \n\tlast_successful_at TIMESTAMP WITH TIME ZONE, \n\tlast_error TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_sync_states PRIMARY KEY (id), \n\tCONSTRAINT ck_sync_states_cursor_nonnegative CHECK (cursor >= 0), \n\tCONSTRAINT ck_sync_states_schema_version_positive CHECK (schema_version >= 1), \n\tCONSTRAINT ck_sync_states_error_length CHECK (last_error IS NULL OR char_length(last_error) <= 1024), \n\tCONSTRAINT uq_sync_states_scope UNIQUE (scope)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE academic_terms (\n\tacademic_session_id UUID NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tstatus VARCHAR(64) NOT NULL, \n\tis_current BOOLEAN DEFAULT false NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_terms PRIMARY KEY (id), \n\tCONSTRAINT fk_academic_terms_academic_session_id_academic_sessions FOREIGN KEY(academic_session_id) REFERENCES academic_sessions (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_terms_session_current ON academic_terms (academic_session_id, is_current)"
    )
    op.execute("CREATE INDEX ix_academic_terms_status ON academic_terms (status)")
    op.execute(
        "CREATE INDEX ix_academic_terms_is_current ON academic_terms (is_current)"
    )
    op.execute(
        "CREATE INDEX ix_academic_terms_academic_session_id ON academic_terms (academic_session_id)"
    )
    op.execute(
        "CREATE INDEX ix_academic_terms_source_deleted_at ON academic_terms (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE departments (\n\tacademic_level_id UUID NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_departments PRIMARY KEY (id), \n\tCONSTRAINT fk_departments_academic_level_id_academic_levels FOREIGN KEY(academic_level_id) REFERENCES academic_levels (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_departments_current_level_name ON departments (academic_level_id, name) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_departments_academic_level_id ON departments (academic_level_id)"
    )
    op.execute(
        "CREATE INDEX ix_departments_level_name ON departments (academic_level_id, name)"
    )
    op.execute(
        "CREATE INDEX ix_departments_source_deleted_at ON departments (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE academic_classes (\n\tacademic_level_id UUID NOT NULL, \n\tarm_label_id UUID NOT NULL, \n\tdisplay_name VARCHAR(255) NOT NULL, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_academic_classes PRIMARY KEY (id), \n\tCONSTRAINT fk_academic_classes_academic_level_id_academic_levels FOREIGN KEY(academic_level_id) REFERENCES academic_levels (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_academic_classes_arm_label_id_arm_labels FOREIGN KEY(arm_label_id) REFERENCES arm_labels (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_academic_classes_is_active ON academic_classes (is_active)"
    )
    op.execute(
        "CREATE INDEX ix_academic_classes_academic_level_id ON academic_classes (academic_level_id)"
    )
    op.execute(
        "CREATE INDEX ix_academic_classes_source_deleted_at ON academic_classes (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_academic_classes_arm_label_id ON academic_classes (arm_label_id)"
    )
    op.execute(
        "CREATE INDEX ix_academic_classes_level_active ON academic_classes (academic_level_id, is_active)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_academic_classes_current_level_arm_label ON academic_classes (academic_level_id, arm_label_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "\nCREATE TABLE curricula (\n\tacademic_level_id UUID NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_curricula PRIMARY KEY (id), \n\tCONSTRAINT fk_curricula_academic_level_id_academic_levels FOREIGN KEY(academic_level_id) REFERENCES academic_levels (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_curricula_academic_level_id ON curricula (academic_level_id)"
    )
    op.execute(
        "CREATE INDEX ix_curricula_source_deleted_at ON curricula (source_deleted_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_curricula_current_level ON curricula (academic_level_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "\nCREATE TABLE assessment_components (\n\tassessment_scheme_id UUID NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tcode VARCHAR(64), \n\tmaximum_score NUMERIC(8, 2) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_assessment_components PRIMARY KEY (id), \n\tCONSTRAINT ck_assessment_components_maximum_positive CHECK (maximum_score > 0), \n\tCONSTRAINT ck_assessment_components_position_nonnegative CHECK (position >= 0), \n\tCONSTRAINT fk_assessment_components_assessment_scheme_id_assessmen_79e0 FOREIGN KEY(assessment_scheme_id) REFERENCES assessment_schemes (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_assessment_components_is_active ON assessment_components (is_active)"
    )
    op.execute(
        "CREATE INDEX ix_assessment_components_source_deleted_at ON assessment_components (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_assessment_components_scheme_active ON assessment_components (assessment_scheme_id, is_active)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_assessment_components_current_scheme_position ON assessment_components (assessment_scheme_id, position) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_assessment_components_assessment_scheme_id ON assessment_components (assessment_scheme_id)"
    )
    op.execute(
        "\nCREATE TABLE local_actor_sessions (\n\tactor_id UUID NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_refreshed_at TIMESTAMP WITH TIME ZONE, \n\tweave_access_token_encrypted TEXT, \n\tweave_access_token_issued_at TIMESTAMP WITH TIME ZONE, \n\tweave_access_token_expires_at TIMESTAMP WITH TIME ZONE, \n\tweave_refresh_token_encrypted TEXT, \n\tweave_refresh_token_expires_at TIMESTAMP WITH TIME ZONE, \n\tweave_auth_state VARCHAR(32) NOT NULL, \n\tweave_refresh_operation_id UUID, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trevocation_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_local_actor_sessions PRIMARY KEY (id), \n\tCONSTRAINT ck_local_actor_sessions_valid_expiry CHECK (expires_at > created_at), \n\tCONSTRAINT ck_local_actor_sessions_valid_revocation CHECK (revoked_at IS NULL OR revoked_at >= created_at), \n\tCONSTRAINT ck_local_actor_sessions_weave_auth_state CHECK (weave_auth_state IN ('legacy', 'synced', 'degraded', 'refresh_pending', 'revoked')), \n\tCONSTRAINT fk_local_actor_sessions_actor_id_local_actors FOREIGN KEY(actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_revoked_at ON local_actor_sessions (revoked_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_actor_revoked ON local_actor_sessions (actor_id, revoked_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_weave_auth_state ON local_actor_sessions (weave_auth_state)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_actor_id ON local_actor_sessions (actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_weave_access_token_expires_at ON local_actor_sessions (weave_access_token_expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_actor_expiry ON local_actor_sessions (actor_id, expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_weave_refresh_token_expires_at ON local_actor_sessions (weave_refresh_token_expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_weave_refresh_operation_id ON local_actor_sessions (weave_refresh_operation_id)"
    )
    op.execute(
        "CREATE INDEX ix_local_actor_sessions_expires_at ON local_actor_sessions (expires_at)"
    )
    op.execute(
        "\nCREATE TABLE media_assets (\n\tstorage_key VARCHAR(512) NOT NULL, \n\toriginal_filename VARCHAR(255) NOT NULL, \n\tmime_type VARCHAR(100) NOT NULL, \n\tsize_bytes BIGINT NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tcreated_by_actor_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_media_assets PRIMARY KEY (id), \n\tCONSTRAINT fk_media_assets_created_by_actor_id_local_actors FOREIGN KEY(created_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute("CREATE INDEX ix_media_assets_sha256 ON media_assets (sha256)")
    op.execute(
        "CREATE INDEX ix_media_assets_mime_type_created ON media_assets (mime_type, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_media_assets_storage_key ON media_assets (storage_key)"
    )
    op.execute(
        "CREATE INDEX ix_media_assets_created_by_actor_id ON media_assets (created_by_actor_id)"
    )
    op.execute(
        "\nCREATE TABLE class_term_departments (\n\tclass_id UUID NOT NULL, \n\tacademic_term_id UUID NOT NULL, \n\tdepartment_id UUID NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_class_term_departments PRIMARY KEY (id), \n\tCONSTRAINT fk_class_term_departments_class_id_academic_classes FOREIGN KEY(class_id) REFERENCES academic_classes (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_class_term_departments_academic_term_id_academic_terms FOREIGN KEY(academic_term_id) REFERENCES academic_terms (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_class_term_departments_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_class_term_departments_current_class_term ON class_term_departments (class_id, academic_term_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_class_term_departments_term_department ON class_term_departments (academic_term_id, department_id)"
    )
    op.execute(
        "CREATE INDEX ix_class_term_departments_department_id ON class_term_departments (department_id)"
    )
    op.execute(
        "CREATE INDEX ix_class_term_departments_academic_term_id ON class_term_departments (academic_term_id)"
    )
    op.execute(
        "CREATE INDEX ix_class_term_departments_class_id ON class_term_departments (class_id)"
    )
    op.execute(
        "CREATE INDEX ix_class_term_departments_source_deleted_at ON class_term_departments (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE curriculum_subjects (\n\tcurriculum_id UUID NOT NULL, \n\tsubject_id UUID NOT NULL, \n\tis_elective BOOLEAN DEFAULT false NOT NULL, \n\telective_group_id UUID, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_curriculum_subjects PRIMARY KEY (id), \n\tCONSTRAINT fk_curriculum_subjects_curriculum_id_curricula FOREIGN KEY(curriculum_id) REFERENCES curricula (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_curriculum_subjects_subject_id_academic_subjects FOREIGN KEY(subject_id) REFERENCES academic_subjects (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_curriculum_subjects_current_curriculum_subject ON curriculum_subjects (curriculum_id, subject_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_is_elective ON curriculum_subjects (is_elective)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_source_deleted_at ON curriculum_subjects (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_curriculum_active ON curriculum_subjects (curriculum_id, is_active)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_subject_id ON curriculum_subjects (subject_id)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_is_active ON curriculum_subjects (is_active)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_elective_group_id ON curriculum_subjects (elective_group_id)"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subjects_curriculum_id ON curriculum_subjects (curriculum_id)"
    )
    op.execute(
        "\nCREATE TABLE student_enrollments (\n\tstudent_id UUID NOT NULL, \n\tadmission_number VARCHAR(128) NOT NULL, \n\tfirst_name VARCHAR(255), \n\tlast_name VARCHAR(255), \n\tacademic_level_id UUID NOT NULL, \n\tclass_id UUID, \n\tacademic_session_id UUID NOT NULL, \n\tis_current BOOLEAN DEFAULT true NOT NULL, \n\tstudent_status VARCHAR(64) NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_student_enrollments PRIMARY KEY (id), \n\tCONSTRAINT fk_student_enrollments_academic_level_id_academic_levels FOREIGN KEY(academic_level_id) REFERENCES academic_levels (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_student_enrollments_class_id_academic_classes FOREIGN KEY(class_id) REFERENCES academic_classes (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_student_enrollments_academic_session_id_academic_sessions FOREIGN KEY(academic_session_id) REFERENCES academic_sessions (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_source_deleted_at ON student_enrollments (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_live_class ON student_enrollments (class_id) WHERE is_current = true AND source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_is_current ON student_enrollments (is_current)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_student_status ON student_enrollments (student_status)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_student_enrollments_current_student ON student_enrollments (student_id) WHERE is_current = true AND source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_academic_session_id ON student_enrollments (academic_session_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_admission_number ON student_enrollments (admission_number)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_academic_level_id ON student_enrollments (academic_level_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_class_id ON student_enrollments (class_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_live_session ON student_enrollments (academic_session_id) WHERE is_current = true AND source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_enrollments_student_id ON student_enrollments (student_id)"
    )
    op.execute(
        "\nCREATE TABLE local_refresh_tokens (\n\tsession_id UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tconsumed_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\treuse_detected_at TIMESTAMP WITH TIME ZONE, \n\treplaced_by_token_id UUID, \n\trefresh_operation_id UUID, \n\treplacement_token_encrypted TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_local_refresh_tokens PRIMARY KEY (id), \n\tCONSTRAINT ck_local_refresh_tokens_valid_expiry CHECK (expires_at > created_at), \n\tCONSTRAINT ck_local_refresh_tokens_valid_consumed_at CHECK (consumed_at IS NULL OR consumed_at >= created_at), \n\tCONSTRAINT ck_local_refresh_tokens_valid_revoked_at CHECK (revoked_at IS NULL OR revoked_at >= created_at), \n\tCONSTRAINT ck_local_refresh_tokens_valid_reuse_at CHECK (reuse_detected_at IS NULL OR reuse_detected_at >= created_at), \n\tCONSTRAINT ck_local_refresh_tokens_not_self_replaced CHECK (replaced_by_token_id IS NULL OR replaced_by_token_id <> id), \n\tCONSTRAINT fk_local_refresh_tokens_session_id_local_actor_sessions FOREIGN KEY(session_id) REFERENCES local_actor_sessions (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_local_refresh_tokens_replaced_by_token_id_local_refr_64b4 FOREIGN KEY(replaced_by_token_id) REFERENCES local_refresh_tokens (id) ON DELETE SET NULL\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_local_refresh_tokens_session_id ON local_refresh_tokens (session_id)"
    )
    op.execute(
        "CREATE INDEX ix_local_refresh_tokens_session_consumed ON local_refresh_tokens (session_id, consumed_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_refresh_tokens_expires_at ON local_refresh_tokens (expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_refresh_tokens_session_expiry ON local_refresh_tokens (session_id, expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_local_refresh_tokens_refresh_operation_id ON local_refresh_tokens (refresh_operation_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_local_refresh_tokens_token_hash ON local_refresh_tokens (token_hash)"
    )
    op.execute(
        "\nCREATE TABLE curriculum_subject_departments (\n\tcurriculum_subject_id UUID NOT NULL, \n\tdepartment_id UUID NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_curriculum_subject_departments PRIMARY KEY (id), \n\tCONSTRAINT fk_curriculum_subject_departments_curriculum_subject_id_ef73 FOREIGN KEY(curriculum_subject_id) REFERENCES curriculum_subjects (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_curriculum_subject_departments_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_curriculum_subject_departments_current_scope ON curriculum_subject_departments (curriculum_subject_id, department_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subject_departments_live_department ON curriculum_subject_departments (department_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subject_departments_live_subject ON curriculum_subject_departments (curriculum_subject_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_curriculum_subject_departments_source_deleted_at ON curriculum_subject_departments (source_deleted_at)"
    )
    op.execute(
        "\nCREATE TABLE student_elective_selections (\n\tstudent_id UUID NOT NULL, \n\telective_group_id UUID NOT NULL, \n\tcurriculum_subject_id UUID NOT NULL, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_student_elective_selections PRIMARY KEY (id), \n\tCONSTRAINT fk_student_elective_selections_curriculum_subject_id_cu_8ca4 FOREIGN KEY(curriculum_subject_id) REFERENCES curriculum_subjects (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_elective_group_id ON student_elective_selections (elective_group_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_live_group_student ON student_elective_selections (elective_group_id, student_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_live_subject_student ON student_elective_selections (curriculum_subject_id, student_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_student_elective_selections_live_student_subject ON student_elective_selections (student_id, curriculum_subject_id) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_student_id ON student_elective_selections (student_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_source_deleted_at ON student_elective_selections (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_student_elective_selections_curriculum_subject_id ON student_elective_selections (curriculum_subject_id)"
    )
    op.execute(
        "\nCREATE TABLE teacher_assignments (\n\tteacher_membership_id UUID NOT NULL, \n\tclass_id UUID NOT NULL, \n\tcurriculum_subject_id UUID NOT NULL, \n\teffective_from DATE NOT NULL, \n\teffective_to DATE, \n\tsynced_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsource_deleted_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_teacher_assignments PRIMARY KEY (id), \n\tCONSTRAINT ck_teacher_assignments_effective_range CHECK (effective_to IS NULL OR effective_to >= effective_from), \n\tCONSTRAINT fk_teacher_assignments_teacher_membership_id_academic_teachers FOREIGN KEY(teacher_membership_id) REFERENCES academic_teachers (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_teacher_assignments_class_id_academic_classes FOREIGN KEY(class_id) REFERENCES academic_classes (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_teacher_assignments_curriculum_subject_id_curriculum_5da4 FOREIGN KEY(curriculum_subject_id) REFERENCES curriculum_subjects (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_curriculum_subject_id ON teacher_assignments (curriculum_subject_id)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_live_teacher_effective ON teacher_assignments (teacher_membership_id, effective_from, effective_to) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_teacher_membership_id ON teacher_assignments (teacher_membership_id)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_source_deleted_at ON teacher_assignments (source_deleted_at)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_effective_to ON teacher_assignments (effective_to)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_class_id ON teacher_assignments (class_id)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_effective_from ON teacher_assignments (effective_from)"
    )
    op.execute(
        "CREATE INDEX ix_teacher_assignments_live_scope_effective ON teacher_assignments (class_id, curriculum_subject_id, effective_from, effective_to) WHERE source_deleted_at IS NULL"
    )
    op.execute(
        "\nCREATE TABLE question_banks (\n\tcurriculum_subject_id UUID NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tdescription TEXT, \n\tcreated_by_actor_id UUID NOT NULL, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_question_banks PRIMARY KEY (id), \n\tCONSTRAINT uq_question_banks_curriculum_subject_name UNIQUE (curriculum_subject_id, name), \n\tCONSTRAINT fk_question_banks_curriculum_subject_id_curriculum_subjects FOREIGN KEY(curriculum_subject_id) REFERENCES curriculum_subjects (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_question_banks_created_by_actor_id_local_actors FOREIGN KEY(created_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_question_banks_curriculum_subject_id ON question_banks (curriculum_subject_id)"
    )
    op.execute(
        "CREATE INDEX ix_question_banks_created_by_actor_id ON question_banks (created_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_question_banks_curriculum_subject_active ON question_banks (curriculum_subject_id, is_active)"
    )
    op.execute(
        "\nCREATE TABLE questions (\n\tbank_id UUID NOT NULL, \n\tquestion_type VARCHAR(15) DEFAULT 'single_choice' NOT NULL, \n\tprompt TEXT NOT NULL, \n\tinstruction TEXT, \n\timage_asset_id UUID, \n\tversion INTEGER DEFAULT 1 NOT NULL, \n\tcreated_by_actor_id UUID NOT NULL, \n\tlast_edited_by_actor_id UUID, \n\tis_active BOOLEAN DEFAULT true NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_questions PRIMARY KEY (id), \n\tCONSTRAINT ck_questions_version_positive CHECK (version >= 1), \n\tCONSTRAINT fk_questions_bank_id_question_banks FOREIGN KEY(bank_id) REFERENCES question_banks (id) ON DELETE RESTRICT, \n\tCONSTRAINT question_type CHECK (question_type IN ('single_choice', 'multiple_choice')), \n\tCONSTRAINT fk_questions_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_questions_created_by_actor_id_local_actors FOREIGN KEY(created_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_questions_last_edited_by_actor_id_local_actors FOREIGN KEY(last_edited_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_questions_bank_active ON questions (bank_id, is_active)"
    )
    op.execute("CREATE INDEX ix_questions_image_asset_id ON questions (image_asset_id)")
    op.execute("CREATE INDEX ix_questions_bank_id ON questions (bank_id)")
    op.execute(
        "CREATE INDEX ix_questions_created_by_actor_id ON questions (created_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_questions_last_edited_by_actor_id ON questions (last_edited_by_actor_id)"
    )
    op.execute(
        "\nCREATE TABLE exams (\n\tsession_id UUID NOT NULL, \n\tterm_id UUID NOT NULL, \n\tcurriculum_subject_id UUID NOT NULL, \n\tquestion_bank_id UUID NOT NULL, \n\tquestion_selection_mode VARCHAR(6) DEFAULT 'random' NOT NULL, \n\tquestion_count INTEGER NOT NULL, \n\tassessment_scheme_id UUID NOT NULL, \n\tassessment_component_id UUID NOT NULL, \n\ttitle VARCHAR(255) NOT NULL, \n\tinstructions TEXT, \n\tfolder_color VARCHAR(7), \n\tduration_minutes INTEGER NOT NULL, \n\tshuffle_questions BOOLEAN DEFAULT true NOT NULL, \n\tshuffle_options BOOLEAN DEFAULT true NOT NULL, \n\tstatus VARCHAR(10) DEFAULT 'draft' NOT NULL, \n\tscheduled_start_at TIMESTAMP WITH TIME ZONE, \n\tlatest_normal_start_at TIMESTAMP WITH TIME ZONE, \n\troster_status VARCHAR(12) DEFAULT 'not_prepared' NOT NULL, \n\troster_version INTEGER DEFAULT 0 NOT NULL, \n\troster_candidate_count INTEGER DEFAULT 0 NOT NULL, \n\troster_prepared_at TIMESTAMP WITH TIME ZONE, \n\troster_error TEXT, \n\tauthoring_version INTEGER DEFAULT 1 NOT NULL, \n\trevision_number INTEGER DEFAULT 1 NOT NULL, \n\trevision_of_exam_id UUID, \n\tcreated_by_actor_id UUID NOT NULL, \n\tlead_teacher_id UUID, \n\tlead_assigned_by_actor_id UUID, \n\tlead_assigned_at TIMESTAMP WITH TIME ZONE, \n\tsubmitted_by_actor_id UUID, \n\tsubmitted_at TIMESTAMP WITH TIME ZONE, \n\tsealed_by_actor_id UUID, \n\tsealed_at TIMESTAMP WITH TIME ZONE, \n\tactivated_by_actor_id UUID, \n\tactivated_at TIMESTAMP WITH TIME ZONE, \n\tclosed_by_actor_id UUID, \n\tclosed_at TIMESTAMP WITH TIME ZONE, \n\tcancelled_by_actor_id UUID, \n\tcancelled_at TIMESTAMP WITH TIME ZONE, \n\tcancellation_reason TEXT, \n\tcomponent_maximum_score NUMERIC(8, 2), \n\tweave_calendar_event_id VARCHAR(128), \n\tcalendar_synced_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exams PRIMARY KEY (id), \n\tCONSTRAINT ck_exams_question_count_positive CHECK (question_count > 0), \n\tCONSTRAINT ck_exams_duration_positive CHECK (duration_minutes > 0), \n\tCONSTRAINT ck_exams_authoring_version_positive CHECK (authoring_version >= 1), \n\tCONSTRAINT ck_exams_revision_positive CHECK (revision_number >= 1), \n\tCONSTRAINT ck_exams_revision_lineage_shape CHECK ((revision_of_exam_id IS NULL AND revision_number = 1) OR (revision_of_exam_id IS NOT NULL AND revision_number > 1)), \n\tCONSTRAINT ck_exams_roster_version_nonnegative CHECK (roster_version >= 0), \n\tCONSTRAINT ck_exams_roster_candidate_count_nonnegative CHECK (roster_candidate_count >= 0), \n\tCONSTRAINT ck_exams_roster_error_length CHECK (roster_error IS NULL OR char_length(roster_error) <= 1024), \n\tCONSTRAINT ck_exams_valid_normal_start_window CHECK (latest_normal_start_at IS NULL OR scheduled_start_at IS NULL OR latest_normal_start_at >= scheduled_start_at), \n\tCONSTRAINT ck_exams_component_maximum_positive CHECK (component_maximum_score IS NULL OR component_maximum_score > 0), \n\tCONSTRAINT ck_exams_lead_assignment_actor_required CHECK (lead_assigned_at IS NULL OR lead_assigned_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exams_submission_actor_required CHECK (submitted_at IS NULL OR submitted_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exams_sealing_actor_required CHECK (sealed_at IS NULL OR sealed_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exams_activation_actor_required CHECK (activated_at IS NULL OR activated_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exams_cancellation_actor_required CHECK (cancelled_at IS NULL OR cancelled_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exams_cancellation_reason_required CHECK (cancelled_at IS NULL OR cancellation_reason IS NOT NULL), \n\tCONSTRAINT fk_exams_session_id_academic_sessions FOREIGN KEY(session_id) REFERENCES academic_sessions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_term_id_academic_terms FOREIGN KEY(term_id) REFERENCES academic_terms (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_curriculum_subject_id_curriculum_subjects FOREIGN KEY(curriculum_subject_id) REFERENCES curriculum_subjects (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_question_bank_id_question_banks FOREIGN KEY(question_bank_id) REFERENCES question_banks (id) ON DELETE RESTRICT, \n\tCONSTRAINT exam_question_selection_mode CHECK (question_selection_mode IN ('random', 'manual')), \n\tCONSTRAINT fk_exams_assessment_scheme_id_assessment_schemes FOREIGN KEY(assessment_scheme_id) REFERENCES assessment_schemes (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_assessment_component_id_assessment_components FOREIGN KEY(assessment_component_id) REFERENCES assessment_components (id) ON DELETE RESTRICT, \n\tCONSTRAINT exam_status CHECK (status IN ('draft', 'submitted', 'sealed', 'active', 'suspended', 'closing', 'cancelling', 'closed', 'cancelled')), \n\tCONSTRAINT exam_roster_status CHECK (roster_status IN ('not_prepared', 'pending', 'building', 'ready', 'stale', 'failed')), \n\tCONSTRAINT fk_exams_revision_of_exam_id_exams FOREIGN KEY(revision_of_exam_id) REFERENCES exams (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_created_by_actor_id_local_actors FOREIGN KEY(created_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_lead_teacher_id_academic_teachers FOREIGN KEY(lead_teacher_id) REFERENCES academic_teachers (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_lead_assigned_by_actor_id_local_actors FOREIGN KEY(lead_assigned_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_submitted_by_actor_id_local_actors FOREIGN KEY(submitted_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_sealed_by_actor_id_local_actors FOREIGN KEY(sealed_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_activated_by_actor_id_local_actors FOREIGN KEY(activated_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_closed_by_actor_id_local_actors FOREIGN KEY(closed_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exams_cancelled_by_actor_id_local_actors FOREIGN KEY(cancelled_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exams_curriculum_subject_id ON exams (curriculum_subject_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_submitted_by_actor_id ON exams (submitted_by_actor_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_exams_revision_of_exam_id ON exams (revision_of_exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_session_term_status ON exams (session_id, term_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_exams_lead_assigned_by_actor_id ON exams (lead_assigned_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_assessment_scheme_id ON exams (assessment_scheme_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_curriculum_subject_status ON exams (curriculum_subject_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_exams_latest_normal_start_at ON exams (latest_normal_start_at)"
    )
    op.execute(
        "CREATE INDEX ix_exams_roster_status_exam_status ON exams (roster_status, status)"
    )
    op.execute("CREATE INDEX ix_exams_question_bank_id ON exams (question_bank_id)")
    op.execute("CREATE INDEX ix_exams_lead_teacher_id ON exams (lead_teacher_id)")
    op.execute("CREATE INDEX ix_exams_scheduled_start_at ON exams (scheduled_start_at)")
    op.execute(
        "CREATE INDEX ix_exams_scheduled_status ON exams (scheduled_start_at, status)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_exams_scope_revision ON exams (term_id, curriculum_subject_id, assessment_component_id, revision_number)"
    )
    op.execute("CREATE INDEX ix_exams_roster_status ON exams (roster_status)")
    op.execute(
        "CREATE INDEX ix_exams_assessment_component_id ON exams (assessment_component_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_created_by_actor_id ON exams (created_by_actor_id)"
    )
    op.execute("CREATE INDEX ix_exams_session_id ON exams (session_id)")
    op.execute(
        "CREATE INDEX ix_exams_question_selection_mode ON exams (question_selection_mode)"
    )
    op.execute(
        "CREATE INDEX ix_exams_cancelled_by_actor_id ON exams (cancelled_by_actor_id)"
    )
    op.execute("CREATE INDEX ix_exams_closed_by_actor_id ON exams (closed_by_actor_id)")
    op.execute("CREATE INDEX ix_exams_term_id ON exams (term_id)")
    op.execute("CREATE INDEX ix_exams_status ON exams (status)")
    op.execute(
        "CREATE INDEX ix_exams_activated_by_actor_id ON exams (activated_by_actor_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_exams_weave_calendar_event_id ON exams (weave_calendar_event_id)"
    )
    op.execute(
        "CREATE INDEX ix_exams_component_status ON exams (assessment_component_id, status)"
    )
    op.execute("CREATE INDEX ix_exams_sealed_by_actor_id ON exams (sealed_by_actor_id)")
    op.execute(
        "\nCREATE TABLE question_ai_import_batches (\n\tdraft_id UUID NOT NULL, \n\tbank_id UUID NOT NULL, \n\tactor_id UUID NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_question_ai_import_batches PRIMARY KEY (id), \n\tCONSTRAINT uq_question_ai_import_batches_draft_id UNIQUE (draft_id), \n\tCONSTRAINT fk_question_ai_import_batches_bank_id_question_banks FOREIGN KEY(bank_id) REFERENCES question_banks (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_question_ai_import_batches_actor_id_local_actors FOREIGN KEY(actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_question_ai_import_batches_actor ON question_ai_import_batches (actor_id, created_at)"
    )
    op.execute(
        "CREATE INDEX ix_question_ai_import_batches_bank ON question_ai_import_batches (bank_id, created_at)"
    )
    op.execute(
        "\nCREATE TABLE question_options (\n\tquestion_id UUID NOT NULL, \n\tposition INTEGER NOT NULL, \n\ttext TEXT, \n\timage_asset_id UUID, \n\tis_correct BOOLEAN DEFAULT false NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_question_options PRIMARY KEY (id), \n\tCONSTRAINT uq_question_options_question_position UNIQUE (question_id, position), \n\tCONSTRAINT ck_question_options_position_positive CHECK (position >= 1), \n\tCONSTRAINT ck_question_options_content_required CHECK (text IS NOT NULL OR image_asset_id IS NOT NULL), \n\tCONSTRAINT fk_question_options_question_id_questions FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_question_options_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_question_options_image_asset_id ON question_options (image_asset_id)"
    )
    op.execute(
        "CREATE INDEX ix_question_options_question_position ON question_options (question_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_question_options_question_id ON question_options (question_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_candidates (\n\texam_id UUID NOT NULL, \n\tenrollment_id UUID NOT NULL, \n\tstudent_id UUID NOT NULL, \n\tclass_id UUID NOT NULL, \n\tadmission_number VARCHAR(128) NOT NULL, \n\tdisplay_name VARCHAR(255) NOT NULL, \n\tstatus VARCHAR(9) DEFAULT 'eligible' NOT NULL, \n\tstatus_reason VARCHAR(500), \n\troster_version INTEGER DEFAULT 1 NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_candidates PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_candidates_exam_enrollment UNIQUE (exam_id, enrollment_id), \n\tCONSTRAINT uq_exam_candidates_exam_student UNIQUE (exam_id, student_id), \n\tCONSTRAINT uq_exam_candidates_exam_admission_number UNIQUE (exam_id, admission_number), \n\tCONSTRAINT ck_exam_candidates_roster_version_positive CHECK (roster_version >= 1), \n\tCONSTRAINT fk_exam_candidates_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_candidates_enrollment_id_student_enrollments FOREIGN KEY(enrollment_id) REFERENCES student_enrollments (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_candidates_class_id_academic_classes FOREIGN KEY(class_id) REFERENCES academic_classes (id) ON DELETE RESTRICT, \n\tCONSTRAINT candidate_status CHECK (status IN ('eligible', 'blocked', 'withdrawn'))\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_candidates_student_id ON exam_candidates (student_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_candidates_admission_number ON exam_candidates (admission_number)"
    )
    op.execute(
        "CREATE INDEX ix_exam_candidates_eligible_student_exam ON exam_candidates (student_id, exam_id) WHERE status = 'eligible'"
    )
    op.execute("CREATE INDEX ix_exam_candidates_status ON exam_candidates (status)")
    op.execute(
        "CREATE INDEX ix_exam_candidates_exam_roster_version ON exam_candidates (exam_id, roster_version)"
    )
    op.execute(
        "CREATE INDEX ix_exam_candidates_exam_class_status ON exam_candidates (exam_id, class_id, status)"
    )
    op.execute("CREATE INDEX ix_exam_candidates_exam_id ON exam_candidates (exam_id)")
    op.execute(
        "CREATE INDEX ix_exam_candidates_exam_status ON exam_candidates (exam_id, status)"
    )
    op.execute(
        "CREATE INDEX ix_exam_candidates_roster_version ON exam_candidates (roster_version)"
    )
    op.execute("CREATE INDEX ix_exam_candidates_class_id ON exam_candidates (class_id)")
    op.execute(
        "CREATE INDEX ix_exam_candidates_enrollment_id ON exam_candidates (enrollment_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_execution_controls (\n\texam_id UUID NOT NULL, \n\toperation VARCHAR(10), \n\toperation_source VARCHAR(9), \n\toperation_requested_at TIMESTAMP WITH TIME ZONE, \n\toperation_requested_by_actor_id UUID, \n\toperation_reason TEXT, \n\toperation_attempts INTEGER DEFAULT 0 NOT NULL, \n\tlast_operation_attempt_at TIMESTAMP WITH TIME ZONE, \n\toperation_error TEXT, \n\tresult_disposition VARCHAR(14), \n\tresults_decided_at TIMESTAMP WITH TIME ZONE, \n\tresults_decided_by_actor_id UUID, \n\tresults_decision_reason TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_execution_controls PRIMARY KEY (id), \n\tCONSTRAINT ck_exam_execution_controls_attempts_nonnegative CHECK (operation_attempts >= 0), \n\tCONSTRAINT ck_exam_execution_controls_error_length CHECK (operation_error IS NULL OR char_length(operation_error) <= 2048), \n\tCONSTRAINT ck_exam_execution_controls_operation_metadata CHECK ((operation IS NULL) OR (operation_source IS NOT NULL AND operation_requested_at IS NOT NULL)), \n\tCONSTRAINT ck_exam_execution_controls_admin_actor CHECK (operation_source != 'admin' OR operation_requested_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exam_execution_controls_cancel_reason CHECK (operation != 'cancelling' OR operation_reason IS NOT NULL), \n\tCONSTRAINT ck_exam_execution_controls_result_decision_metadata CHECK (result_disposition NOT IN ('approved', 'voided') OR (results_decided_at IS NOT NULL AND results_decided_by_actor_id IS NOT NULL)), \n\tCONSTRAINT ck_exam_execution_controls_result_reason_length CHECK (results_decision_reason IS NULL OR char_length(results_decision_reason) <= 1000), \n\tCONSTRAINT fk_exam_execution_controls_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE CASCADE, \n\tCONSTRAINT exam_execution_operation CHECK (operation IN ('closing', 'cancelling')), \n\tCONSTRAINT exam_operation_source CHECK (operation_source IN ('admin', 'automatic')), \n\tCONSTRAINT fk_exam_execution_controls_operation_requested_by_actor_8227 FOREIGN KEY(operation_requested_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT exam_result_disposition CHECK (result_disposition IN ('pending_review', 'approved', 'voided')), \n\tCONSTRAINT fk_exam_execution_controls_results_decided_by_actor_id__5617 FOREIGN KEY(results_decided_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_result_disposition ON exam_execution_controls (result_disposition, exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_operation ON exam_execution_controls (operation)"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_operation_requested ON exam_execution_controls (operation, operation_requested_at)"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_operation_requested_at ON exam_execution_controls (operation_requested_at)"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_operation_requested_by_actor_id ON exam_execution_controls (operation_requested_by_actor_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_exam_execution_controls_exam_id ON exam_execution_controls (exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_execution_controls_results_decided_by_actor_id ON exam_execution_controls (results_decided_by_actor_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_question_selections (\n\texam_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\tadded_by_actor_id UUID NOT NULL, \n\tposition INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_question_selections PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_question_selections_exam_question UNIQUE (exam_id, question_id), \n\tCONSTRAINT uq_exam_question_selections_exam_position UNIQUE (exam_id, position), \n\tCONSTRAINT ck_exam_question_selections_position_positive CHECK (position >= 1), \n\tCONSTRAINT fk_exam_question_selections_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_exam_question_selections_question_id_questions FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_question_selections_added_by_actor_id_local_actors FOREIGN KEY(added_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_selections_added_by_actor_id ON exam_question_selections (added_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_selections_exam_position ON exam_question_selections (exam_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_selections_question_id ON exam_question_selections (question_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_selections_exam_id ON exam_question_selections (exam_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_target_classes (\n\texam_id UUID NOT NULL, \n\tclass_id UUID NOT NULL, \n\tteacher_assignment_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_target_classes PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_target_classes_exam_class UNIQUE (exam_id, class_id), \n\tCONSTRAINT fk_exam_target_classes_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_exam_target_classes_class_id_academic_classes FOREIGN KEY(class_id) REFERENCES academic_classes (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_target_classes_teacher_assignment_id_teacher_as_c830 FOREIGN KEY(teacher_assignment_id) REFERENCES teacher_assignments (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_target_classes_exam_id ON exam_target_classes (exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_target_classes_assignment ON exam_target_classes (teacher_assignment_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_target_classes_teacher_assignment_id ON exam_target_classes (teacher_assignment_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_target_classes_class_exam ON exam_target_classes (class_id, exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_target_classes_class_id ON exam_target_classes (class_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_invigilators (\n\texam_id UUID NOT NULL, \n\tteacher_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_invigilators PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_invigilators_exam_teacher UNIQUE (exam_id, teacher_id), \n\tCONSTRAINT fk_exam_invigilators_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_exam_invigilators_teacher_id_academic_teachers FOREIGN KEY(teacher_id) REFERENCES academic_teachers (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_invigilators_teacher_id ON exam_invigilators (teacher_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_invigilators_teacher_exam ON exam_invigilators (teacher_id, exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_invigilators_exam_id ON exam_invigilators (exam_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_suspensions (\n\texam_id UUID NOT NULL, \n\tsource VARCHAR(6) NOT NULL, \n\tsuspended_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsuspended_by_actor_id UUID, \n\treason TEXT NOT NULL, \n\tresumed_at TIMESTAMP WITH TIME ZONE, \n\tresumed_by_actor_id UUID, \n\tresume_reason TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_suspensions PRIMARY KEY (id), \n\tCONSTRAINT ck_exam_suspensions_resume_after_suspend CHECK (resumed_at IS NULL OR resumed_at >= suspended_at), \n\tCONSTRAINT ck_exam_suspensions_resume_actor_required CHECK (resumed_at IS NULL OR resumed_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_exam_suspensions_admin_actor_required CHECK ((source != 'admin') OR (suspended_by_actor_id IS NOT NULL)), \n\tCONSTRAINT fk_exam_suspensions_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE RESTRICT, \n\tCONSTRAINT exam_suspension_source CHECK (source IN ('admin', 'system')), \n\tCONSTRAINT fk_exam_suspensions_suspended_by_actor_id_local_actors FOREIGN KEY(suspended_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_suspensions_resumed_by_actor_id_local_actors FOREIGN KEY(resumed_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_suspensions_suspended_by_actor_id ON exam_suspensions (suspended_by_actor_id)"
    )
    op.execute("CREATE INDEX ix_exam_suspensions_exam_id ON exam_suspensions (exam_id)")
    op.execute(
        "CREATE INDEX ix_exam_suspensions_resumed_by_actor_id ON exam_suspensions (resumed_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_suspensions_exam_suspended_at ON exam_suspensions (exam_id, suspended_at)"
    )
    op.execute(
        "\nCREATE TABLE exam_questions (\n\texam_id UUID NOT NULL, \n\tsource_question_id UUID NOT NULL, \n\tsource_question_version INTEGER NOT NULL, \n\tadded_by_actor_id UUID, \n\tquestion_type VARCHAR(15) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tprompt TEXT NOT NULL, \n\tinstruction TEXT, \n\timage_asset_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_questions PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_questions_exam_source_question UNIQUE (exam_id, source_question_id), \n\tCONSTRAINT uq_exam_questions_exam_position UNIQUE (exam_id, position), \n\tCONSTRAINT ck_exam_questions_source_version_positive CHECK (source_question_version >= 1), \n\tCONSTRAINT ck_exam_questions_position_positive CHECK (position >= 1), \n\tCONSTRAINT fk_exam_questions_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_exam_questions_source_question_id_questions FOREIGN KEY(source_question_id) REFERENCES questions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_questions_added_by_actor_id_local_actors FOREIGN KEY(added_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT exam_question_type CHECK (question_type IN ('single_choice', 'multiple_choice')), \n\tCONSTRAINT fk_exam_questions_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_questions_image_asset_id ON exam_questions (image_asset_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_questions_added_by_actor_id ON exam_questions (added_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_questions_source_question_id ON exam_questions (source_question_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_questions_exam_position ON exam_questions (exam_id, position)"
    )
    op.execute("CREATE INDEX ix_exam_questions_exam_id ON exam_questions (exam_id)")
    op.execute(
        "\nCREATE TABLE question_ai_import_items (\n\tbatch_id UUID NOT NULL, \n\tquestion_id UUID NOT NULL, \n\tposition INTEGER NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_question_ai_import_items PRIMARY KEY (id), \n\tCONSTRAINT uq_question_ai_import_items_batch_position UNIQUE (batch_id, position), \n\tCONSTRAINT uq_question_ai_import_items_batch_question UNIQUE (batch_id, question_id), \n\tCONSTRAINT fk_question_ai_import_items_batch_id_question_ai_import_batches FOREIGN KEY(batch_id) REFERENCES question_ai_import_batches (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_question_ai_import_items_question_id_questions FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_question_ai_import_items_question ON question_ai_import_items (question_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_attempts (\n\tcandidate_id UUID NOT NULL, \n\tstatus VARCHAR(11) DEFAULT 'in_progress' NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\ttime_limit_seconds INTEGER NOT NULL, \n\telapsed_seconds INTEGER DEFAULT 0 NOT NULL, \n\tactive_since TIMESTAMP WITH TIME ZONE, \n\tlast_heartbeat_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_activity_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tended_at TIMESTAMP WITH TIME ZONE, \n\tend_reason VARCHAR(19), \n\ttermination_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_attempts PRIMARY KEY (id), \n\tCONSTRAINT ck_exam_attempts_time_limit_positive CHECK (time_limit_seconds > 0), \n\tCONSTRAINT ck_exam_attempts_elapsed_nonnegative CHECK (elapsed_seconds >= 0), \n\tCONSTRAINT ck_exam_attempts_elapsed_within_limit CHECK (elapsed_seconds <= time_limit_seconds), \n\tCONSTRAINT ck_exam_attempts_valid_active_since CHECK (active_since IS NULL OR active_since >= started_at), \n\tCONSTRAINT ck_exam_attempts_valid_heartbeat CHECK (last_heartbeat_at >= started_at), \n\tCONSTRAINT ck_exam_attempts_valid_activity CHECK (last_activity_at >= started_at), \n\tCONSTRAINT ck_exam_attempts_valid_end CHECK (ended_at IS NULL OR ended_at >= started_at), \n\tCONSTRAINT ck_exam_attempts_active_segment_matches_status CHECK ((status = 'in_progress' AND active_since IS NOT NULL) OR (status <> 'in_progress' AND active_since IS NULL)), \n\tCONSTRAINT ck_exam_attempts_terminal_state_consistent CHECK ((status IN ('in_progress', 'interrupted') AND ended_at IS NULL AND end_reason IS NULL) OR (status IN ('submitted', 'terminated') AND ended_at IS NOT NULL AND end_reason IS NOT NULL)), \n\tCONSTRAINT ck_exam_attempts_termination_reason_consistent CHECK ((status = 'terminated' AND end_reason IN ('admin_terminated', 'exam_cancelled') AND termination_reason IS NOT NULL) OR (status <> 'terminated' AND termination_reason IS NULL)), \n\tCONSTRAINT ck_exam_attempts_submitted_not_admin_terminated CHECK (status <> 'submitted' OR end_reason NOT IN ('admin_terminated', 'exam_cancelled')), \n\tCONSTRAINT fk_exam_attempts_candidate_id_exam_candidates FOREIGN KEY(candidate_id) REFERENCES exam_candidates (id) ON DELETE RESTRICT, \n\tCONSTRAINT attempt_status CHECK (status IN ('in_progress', 'interrupted', 'submitted', 'terminated')), \n\tCONSTRAINT attempt_end_reason CHECK (end_reason IN ('candidate_submitted', 'time_expired', 'exam_closed', 'exam_cancelled', 'admin_terminated'))\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_attempts_status_heartbeat ON exam_attempts (status, last_heartbeat_at)"
    )
    op.execute(
        "CREATE INDEX ix_exam_attempts_last_heartbeat_at ON exam_attempts (last_heartbeat_at)"
    )
    op.execute("CREATE INDEX ix_exam_attempts_status ON exam_attempts (status)")
    op.execute(
        "CREATE UNIQUE INDEX ix_exam_attempts_candidate_id ON exam_attempts (candidate_id)"
    )
    op.execute(
        "\nCREATE TABLE candidate_late_start_authorizations (\n\tcandidate_id UUID NOT NULL, \n\tgranted_by_actor_id UUID NOT NULL, \n\treason TEXT NOT NULL, \n\tgranted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE, \n\tconsumed_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trevoked_by_actor_id UUID, \n\trevocation_reason TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_candidate_late_start_authorizations PRIMARY KEY (id), \n\tCONSTRAINT ck_candidate_late_start_expiry_valid CHECK (expires_at IS NULL OR expires_at >= granted_at), \n\tCONSTRAINT ck_candidate_late_start_consumed_valid CHECK (consumed_at IS NULL OR consumed_at >= granted_at), \n\tCONSTRAINT ck_candidate_late_start_revoked_valid CHECK (revoked_at IS NULL OR revoked_at >= granted_at), \n\tCONSTRAINT ck_candidate_late_start_revocation_actor_required CHECK (revoked_at IS NULL OR revoked_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_candidate_late_start_revocation_reason_required CHECK (revoked_at IS NULL OR revocation_reason IS NOT NULL), \n\tCONSTRAINT ck_candidate_late_start_not_consumed_and_revoked CHECK (NOT (consumed_at IS NOT NULL AND revoked_at IS NOT NULL)), \n\tCONSTRAINT fk_candidate_late_start_authorizations_candidate_id_exa_17f9 FOREIGN KEY(candidate_id) REFERENCES exam_candidates (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_candidate_late_start_authorizations_granted_by_actor_7d04 FOREIGN KEY(granted_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_candidate_late_start_authorizations_revoked_by_actor_53e7 FOREIGN KEY(revoked_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_candidate_late_start_authorizations_granted_by_actor_id ON candidate_late_start_authorizations (granted_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_late_start_authorizations_revoked_by_actor_id ON candidate_late_start_authorizations (revoked_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_late_start_candidate_granted ON candidate_late_start_authorizations (candidate_id, granted_at)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_late_start_authorizations_granted_at ON candidate_late_start_authorizations (granted_at)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_late_start_authorizations_candidate_id ON candidate_late_start_authorizations (candidate_id)"
    )
    op.execute(
        "\nCREATE TABLE candidate_make_up_authorizations (\n\tcandidate_id UUID NOT NULL, \n\tapproved_by_actor_id UUID NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\tapproved_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tconsumed_at TIMESTAMP WITH TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trevoked_by_actor_id UUID, \n\trevocation_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_candidate_make_up_authorizations PRIMARY KEY (id), \n\tCONSTRAINT ck_candidate_makeup_consumed_valid CHECK (consumed_at IS NULL OR consumed_at >= approved_at), \n\tCONSTRAINT ck_candidate_makeup_revoked_valid CHECK (revoked_at IS NULL OR revoked_at >= approved_at), \n\tCONSTRAINT ck_candidate_makeup_revocation_actor_required CHECK (revoked_at IS NULL OR revoked_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_candidate_makeup_revocation_reason_required CHECK (revoked_at IS NULL OR revocation_reason IS NOT NULL), \n\tCONSTRAINT ck_candidate_makeup_not_consumed_and_revoked CHECK (NOT (consumed_at IS NOT NULL AND revoked_at IS NOT NULL)), \n\tCONSTRAINT fk_candidate_make_up_authorizations_candidate_id_exam_c_5b2f FOREIGN KEY(candidate_id) REFERENCES exam_candidates (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_candidate_make_up_authorizations_approved_by_actor_i_139e FOREIGN KEY(approved_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_candidate_make_up_authorizations_revoked_by_actor_id_835b FOREIGN KEY(revoked_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_candidate_makeup_candidate_approved ON candidate_make_up_authorizations (candidate_id, approved_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_candidate_makeup_one_active ON candidate_make_up_authorizations (candidate_id) WHERE revoked_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_candidate_make_up_authorizations_revoked_by_actor_id ON candidate_make_up_authorizations (revoked_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_make_up_authorizations_approved_at ON candidate_make_up_authorizations (approved_at)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_make_up_authorizations_approved_by_actor_id ON candidate_make_up_authorizations (approved_by_actor_id)"
    )
    op.execute(
        "CREATE INDEX ix_candidate_make_up_authorizations_candidate_id ON candidate_make_up_authorizations (candidate_id)"
    )
    op.execute(
        "\nCREATE TABLE exam_question_options (\n\texam_question_id UUID NOT NULL, \n\tposition INTEGER NOT NULL, \n\ttext TEXT, \n\timage_asset_id UUID, \n\tis_correct BOOLEAN DEFAULT false NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_question_options PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_question_options_question_position UNIQUE (exam_question_id, position), \n\tCONSTRAINT ck_exam_question_options_position_positive CHECK (position >= 1), \n\tCONSTRAINT ck_exam_question_options_content_required CHECK (text IS NOT NULL OR image_asset_id IS NOT NULL), \n\tCONSTRAINT fk_exam_question_options_exam_question_id_exam_questions FOREIGN KEY(exam_question_id) REFERENCES exam_questions (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_exam_question_options_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_options_exam_question_id ON exam_question_options (exam_question_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_options_question_position ON exam_question_options (exam_question_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_exam_question_options_image_asset_id ON exam_question_options (image_asset_id)"
    )
    op.execute(
        "\nCREATE TABLE attempt_interruptions (\n\tattempt_id UUID NOT NULL, \n\tinterrupted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tremaining_seconds INTEGER NOT NULL, \n\treason VARCHAR(500) NOT NULL, \n\tresumed_at TIMESTAMP WITH TIME ZONE, \n\tresumed_by_actor_id UUID, \n\tresume_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_attempt_interruptions PRIMARY KEY (id), \n\tCONSTRAINT ck_attempt_interruptions_remaining_nonnegative CHECK (remaining_seconds >= 0), \n\tCONSTRAINT ck_attempt_interruptions_valid_resume CHECK (resumed_at IS NULL OR resumed_at >= interrupted_at), \n\tCONSTRAINT ck_attempt_interruptions_resume_actor_required CHECK (resumed_at IS NULL OR resumed_by_actor_id IS NOT NULL), \n\tCONSTRAINT ck_attempt_interruptions_resume_reason_required CHECK (resumed_at IS NULL OR resume_reason IS NOT NULL), \n\tCONSTRAINT fk_attempt_interruptions_attempt_id_exam_attempts FOREIGN KEY(attempt_id) REFERENCES exam_attempts (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_attempt_interruptions_resumed_by_actor_id_local_actors FOREIGN KEY(resumed_by_actor_id) REFERENCES local_actors (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_attempt_interruptions_one_open ON attempt_interruptions (attempt_id) WHERE resumed_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_attempt_interruptions_attempt_id ON attempt_interruptions (attempt_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_interruptions_attempt_interrupted ON attempt_interruptions (attempt_id, interrupted_at)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_interruptions_resumed_by_actor_id ON attempt_interruptions (resumed_by_actor_id)"
    )
    op.execute(
        "\nCREATE TABLE attempt_question_allocations (\n\tattempt_id UUID NOT NULL, \n\texam_question_id UUID, \n\tsource_question_id UUID NOT NULL, \n\tsource_question_version INTEGER NOT NULL, \n\tquestion_type VARCHAR(15) NOT NULL, \n\tposition INTEGER NOT NULL, \n\tprompt TEXT NOT NULL, \n\tinstruction TEXT, \n\timage_asset_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_attempt_question_allocations PRIMARY KEY (id), \n\tCONSTRAINT uq_attempt_questions_attempt_source_question UNIQUE (attempt_id, source_question_id), \n\tCONSTRAINT uq_attempt_questions_attempt_position UNIQUE (attempt_id, position), \n\tCONSTRAINT ck_attempt_questions_source_version_positive CHECK (source_question_version >= 1), \n\tCONSTRAINT ck_attempt_questions_position_positive CHECK (position >= 1), \n\tCONSTRAINT fk_attempt_question_allocations_attempt_id_exam_attempts FOREIGN KEY(attempt_id) REFERENCES exam_attempts (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_attempt_question_allocations_exam_question_id_exam_questions FOREIGN KEY(exam_question_id) REFERENCES exam_questions (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_attempt_question_allocations_source_question_id_questions FOREIGN KEY(source_question_id) REFERENCES questions (id) ON DELETE RESTRICT, \n\tCONSTRAINT attempt_question_type CHECK (question_type IN ('single_choice', 'multiple_choice')), \n\tCONSTRAINT fk_attempt_question_allocations_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_attempt_question_allocations_exam_question_id ON attempt_question_allocations (exam_question_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_question_allocations_image_asset_id ON attempt_question_allocations (image_asset_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_questions_attempt_position ON attempt_question_allocations (attempt_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_question_allocations_source_question_id ON attempt_question_allocations (source_question_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_question_allocations_attempt_id ON attempt_question_allocations (attempt_id)"
    )
    op.execute(
        "\nCREATE TABLE student_exam_sessions (\n\tstudent_id UUID NOT NULL, \n\tcandidate_id UUID, \n\texam_id UUID, \n\tmakeup_authorization_id UUID, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\trevocation_reason VARCHAR(500), \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_student_exam_sessions PRIMARY KEY (id), \n\tCONSTRAINT ck_student_exam_sessions_valid_expiry CHECK (expires_at > created_at), \n\tCONSTRAINT ck_student_exam_sessions_valid_revocation CHECK (revoked_at IS NULL OR revoked_at >= created_at), \n\tCONSTRAINT ck_student_exam_sessions_revocation_reason_required CHECK (revoked_at IS NULL OR revocation_reason IS NOT NULL), \n\tCONSTRAINT ck_student_exam_sessions_binding_pair CHECK ((candidate_id IS NULL AND exam_id IS NULL) OR (candidate_id IS NOT NULL AND exam_id IS NOT NULL)), \n\tCONSTRAINT ck_student_exam_sessions_makeup_requires_binding CHECK (makeup_authorization_id IS NULL OR candidate_id IS NOT NULL), \n\tCONSTRAINT fk_student_exam_sessions_candidate_id_exam_candidates FOREIGN KEY(candidate_id) REFERENCES exam_candidates (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_student_exam_sessions_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_student_exam_sessions_makeup_authorization_id_candid_55e2 FOREIGN KEY(makeup_authorization_id) REFERENCES candidate_make_up_authorizations (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_exam_id ON student_exam_sessions (exam_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_expires_at ON student_exam_sessions (expires_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_student_exam_sessions_token_hash ON student_exam_sessions (token_hash)"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_student_id ON student_exam_sessions (student_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_revoked_at ON student_exam_sessions (revoked_at)"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_candidate_id ON student_exam_sessions (candidate_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_student_exam_sessions_one_active_candidate ON student_exam_sessions (candidate_id) WHERE revoked_at IS NULL AND candidate_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_makeup_authorization_id ON student_exam_sessions (makeup_authorization_id)"
    )
    op.execute(
        "CREATE INDEX ix_student_exam_sessions_student_expiry ON student_exam_sessions (student_id, expires_at)"
    )
    op.execute(
        "\nCREATE TABLE exam_results (\n\tattempt_id UUID NOT NULL, \n\tcandidate_id UUID NOT NULL, \n\texam_id UUID NOT NULL, \n\tassessment_component_id UUID NOT NULL, \n\traw_score INTEGER NOT NULL, \n\traw_max_score INTEGER NOT NULL, \n\tpercentage NUMERIC(5, 2) NOT NULL, \n\tcomponent_score NUMERIC(8, 2) NOT NULL, \n\tcomponent_maximum_score NUMERIC(8, 2) NOT NULL, \n\tcalculated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tsync_status VARCHAR(7) DEFAULT 'pending' NOT NULL, \n\tsync_batch_id UUID, \n\tsync_attempts INTEGER DEFAULT 0 NOT NULL, \n\tlast_sync_attempt_at TIMESTAMP WITH TIME ZONE, \n\tsynced_at TIMESTAMP WITH TIME ZONE, \n\tsync_error TEXT, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_exam_results PRIMARY KEY (id), \n\tCONSTRAINT uq_exam_results_candidate_exam UNIQUE (candidate_id, exam_id), \n\tCONSTRAINT ck_exam_results_raw_score_nonnegative CHECK (raw_score >= 0), \n\tCONSTRAINT ck_exam_results_raw_max_positive CHECK (raw_max_score > 0), \n\tCONSTRAINT ck_exam_results_raw_score_within_max CHECK (raw_score <= raw_max_score), \n\tCONSTRAINT ck_exam_results_percentage_nonnegative CHECK (percentage >= 0), \n\tCONSTRAINT ck_exam_results_percentage_within_100 CHECK (percentage <= 100), \n\tCONSTRAINT ck_exam_results_component_score_nonnegative CHECK (component_score >= 0), \n\tCONSTRAINT ck_exam_results_component_max_positive CHECK (component_maximum_score > 0), \n\tCONSTRAINT ck_exam_results_component_score_within_max CHECK (component_score <= component_maximum_score), \n\tCONSTRAINT ck_exam_results_sync_attempts_nonnegative CHECK (sync_attempts >= 0), \n\tCONSTRAINT ck_exam_results_sync_error_length CHECK (sync_error IS NULL OR char_length(sync_error) <= 1024), \n\tCONSTRAINT ck_exam_results_synced_at_matches_status CHECK (synced_at IS NULL OR sync_status = 'synced'), \n\tCONSTRAINT ck_exam_results_syncing_requires_batch CHECK (sync_status != 'syncing' OR sync_batch_id IS NOT NULL), \n\tCONSTRAINT ck_exam_results_synced_requires_batch CHECK (sync_status != 'synced' OR sync_batch_id IS NOT NULL), \n\tCONSTRAINT fk_exam_results_attempt_id_exam_attempts FOREIGN KEY(attempt_id) REFERENCES exam_attempts (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_results_candidate_id_exam_candidates FOREIGN KEY(candidate_id) REFERENCES exam_candidates (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_results_exam_id_exams FOREIGN KEY(exam_id) REFERENCES exams (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_exam_results_assessment_component_id_assessment_components FOREIGN KEY(assessment_component_id) REFERENCES assessment_components (id) ON DELETE RESTRICT, \n\tCONSTRAINT result_sync_status CHECK (sync_status IN ('pending', 'syncing', 'synced', 'failed'))\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_sync_batch_status ON exam_results (sync_batch_id, sync_status)"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_exam_results_attempt_id ON exam_results (attempt_id)"
    )
    op.execute("CREATE INDEX ix_exam_results_exam_id ON exam_results (exam_id)")
    op.execute(
        "CREATE INDEX ix_exam_results_assessment_component_id ON exam_results (assessment_component_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_sync_batch_id ON exam_results (sync_batch_id)"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_exam_sync_status ON exam_results (exam_id, sync_status)"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_component_sync_status ON exam_results (assessment_component_id, sync_status)"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_sync_status_attempt ON exam_results (sync_status, last_sync_attempt_at)"
    )
    op.execute(
        "CREATE INDEX ix_exam_results_candidate_id ON exam_results (candidate_id)"
    )
    op.execute("CREATE INDEX ix_exam_results_sync_status ON exam_results (sync_status)")
    op.execute(
        "\nCREATE TABLE attempt_option_allocations (\n\tattempt_question_id UUID NOT NULL, \n\texam_question_option_id UUID, \n\tsource_question_option_id UUID, \n\tposition INTEGER NOT NULL, \n\ttext TEXT, \n\timage_asset_id UUID, \n\tis_correct BOOLEAN DEFAULT false NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_attempt_option_allocations PRIMARY KEY (id), \n\tCONSTRAINT uq_attempt_options_question_position UNIQUE (attempt_question_id, position), \n\tCONSTRAINT ck_attempt_options_exactly_one_source CHECK ((exam_question_option_id IS NOT NULL AND source_question_option_id IS NULL) OR (exam_question_option_id IS NULL AND source_question_option_id IS NOT NULL)), \n\tCONSTRAINT ck_attempt_options_content_required CHECK (text IS NOT NULL OR image_asset_id IS NOT NULL), \n\tCONSTRAINT ck_attempt_options_position_positive CHECK (position >= 1), \n\tCONSTRAINT fk_attempt_option_allocations_attempt_question_id_attem_3686 FOREIGN KEY(attempt_question_id) REFERENCES attempt_question_allocations (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_attempt_option_allocations_exam_question_option_id_e_ea38 FOREIGN KEY(exam_question_option_id) REFERENCES exam_question_options (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_attempt_option_allocations_source_question_option_id_24ca FOREIGN KEY(source_question_option_id) REFERENCES question_options (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_attempt_option_allocations_image_asset_id_media_assets FOREIGN KEY(image_asset_id) REFERENCES media_assets (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_attempt_option_allocations_source_question_option_id ON attempt_option_allocations (source_question_option_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_option_allocations_attempt_question_id ON attempt_option_allocations (attempt_question_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_attempt_options_exam_source ON attempt_option_allocations (attempt_question_id, exam_question_option_id) WHERE exam_question_option_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_attempt_options_bank_source ON attempt_option_allocations (attempt_question_id, source_question_option_id) WHERE source_question_option_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_attempt_option_allocations_exam_question_option_id ON attempt_option_allocations (exam_question_option_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_options_question_position ON attempt_option_allocations (attempt_question_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_option_allocations_image_asset_id ON attempt_option_allocations (image_asset_id)"
    )
    op.execute(
        "\nCREATE TABLE attempt_answers (\n\tattempt_question_id UUID NOT NULL, \n\tis_flagged BOOLEAN DEFAULT false NOT NULL, \n\tmutation_sequence INTEGER DEFAULT 0 NOT NULL, \n\tanswered_at TIMESTAMP WITH TIME ZONE, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_attempt_answers PRIMARY KEY (id), \n\tCONSTRAINT ck_attempt_answers_mutation_sequence_nonnegative CHECK (mutation_sequence >= 0), \n\tCONSTRAINT fk_attempt_answers_attempt_question_id_attempt_question_2940 FOREIGN KEY(attempt_question_id) REFERENCES attempt_question_allocations (id) ON DELETE CASCADE\n)\n\n"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_attempt_answers_attempt_question_id ON attempt_answers (attempt_question_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_answers_updated ON attempt_answers (updated_at)"
    )
    op.execute(
        "\nCREATE TABLE attempt_answer_selections (\n\tanswer_id UUID NOT NULL, \n\tattempt_option_id UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tid UUID NOT NULL, \n\tCONSTRAINT pk_attempt_answer_selections PRIMARY KEY (id), \n\tCONSTRAINT uq_attempt_answer_selections_answer_option UNIQUE (answer_id, attempt_option_id), \n\tCONSTRAINT fk_attempt_answer_selections_answer_id_attempt_answers FOREIGN KEY(answer_id) REFERENCES attempt_answers (id) ON DELETE CASCADE, \n\tCONSTRAINT fk_attempt_answer_selections_attempt_option_id_attempt__6f32 FOREIGN KEY(attempt_option_id) REFERENCES attempt_option_allocations (id) ON DELETE RESTRICT\n)\n\n"
    )
    op.execute(
        "CREATE INDEX ix_attempt_answer_selections_answer_id ON attempt_answer_selections (answer_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_answer_selections_answer ON attempt_answer_selections (answer_id)"
    )
    op.execute(
        "CREATE INDEX ix_attempt_answer_selections_attempt_option_id ON attempt_answer_selections (attempt_option_id)"
    )
    op.execute(
        "\n        CREATE FUNCTION public.weave_cbt_fill_selection_contributor()\n        RETURNS trigger LANGUAGE plpgsql AS $$\n        BEGIN\n            IF NEW.added_by_actor_id IS NULL THEN\n                SELECT COALESCE(frozen.added_by_actor_id, exam.created_by_actor_id)\n                INTO NEW.added_by_actor_id\n                FROM public.exams AS exam\n                LEFT JOIN public.exam_questions AS frozen\n                  ON frozen.exam_id = exam.revision_of_exam_id\n                 AND frozen.source_question_id = NEW.question_id\n                WHERE exam.id = NEW.exam_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $$\n        "
    )
    op.execute(
        "\n        CREATE TRIGGER trg_exam_selection_contributor\n        BEFORE INSERT ON public.exam_question_selections\n        FOR EACH ROW EXECUTE FUNCTION public.weave_cbt_fill_selection_contributor()\n        "
    )
    op.execute(
        "\n        CREATE FUNCTION public.weave_cbt_fill_frozen_contributor()\n        RETURNS trigger LANGUAGE plpgsql AS $$\n        BEGIN\n            IF NEW.added_by_actor_id IS NULL THEN\n                SELECT selection.added_by_actor_id INTO NEW.added_by_actor_id\n                FROM public.exam_question_selections AS selection\n                WHERE selection.exam_id = NEW.exam_id\n                  AND selection.question_id = NEW.source_question_id;\n            END IF;\n            RETURN NEW;\n        END;\n        $$\n        "
    )
    op.execute(
        "\n        CREATE TRIGGER trg_exam_question_contributor\n        BEFORE INSERT ON public.exam_questions\n        FOR EACH ROW EXECUTE FUNCTION public.weave_cbt_fill_frozen_contributor()\n        "
    )


def downgrade():
    raise RuntimeError(
        "Initial schema downgrade would erase school data; restore a backup instead."
    )
