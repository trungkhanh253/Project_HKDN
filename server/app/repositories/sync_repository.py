class SyncRepository:
    @staticmethod
    def pull_changes_by_seq(model_class, after_seq: int, limit: int = 100):
        """
        Lấy danh sách bản ghi thay đổi dựa vào cột seq lớn hơn after_seq.
        """
        return (
            model_class.query
            .filter(model_class.seq > after_seq)
            .order_by(model_class.seq.asc())
            .limit(limit)
            .all()
        )